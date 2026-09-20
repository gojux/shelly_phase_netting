import logging
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.shelly_phase_netting.const import DOMAIN
from custom_components.shelly_phase_netting.history import build_rows

from .test_integration import fill, setup_entry

HOUR = 3600
IMPORT_ENTITY = "sensor.test_netted_grid_import"
EXPORT_ENTITY = "sensor.test_netted_grid_export"


def row_start(row):
    start = row["start"]
    return int(start.timestamp() if hasattr(start, "timestamp") else start)


def hourly_expected(records, first_ts):
    """Independent re-computation: {hour: [import_wh, export_wh]} of all records >= first_ts."""
    hourly = {}
    for ts, values in sorted(records.items()):
        if ts < first_ts:
            continue
        net = sum(values[i] - values[i + 1] for i in (0, 2, 4))
        bucket = hourly.setdefault(ts // HOUR * HOUR, [0.0, 0.0])
        bucket[0 if net >= 0 else 1] += abs(net)
    return hourly


async def read_statistics(hass, entity_id, start):
    await async_wait_recording_done(hass)
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass, datetime.fromtimestamp(start, timezone.utc), None, {entity_id}, "hour", None,
        {"state", "sum"},
    )
    return result.get(entity_id, [])


def fixed_clock():
    """A 'now' of hh:07:30 two hours ago, and the frozen clock for the coordinator only."""
    now = (int(time.time()) // HOUR) * HOUR - 2 * HOUR + 7 * 60 + 30
    return now, patch(
        "custom_components.shelly_phase_netting.coordinator.time", SimpleNamespace(time=lambda: now)
    )


def test_build_rows_uses_first_hour_as_baseline_and_leaves_cursor_hour_open():
    hourly = {0: 100.0, HOUR: 200.0, 2 * HOUR: 300.0, 3 * HOUR: 400.0}
    rows = build_rows(hourly, cursor=3 * HOUR + 120)   # cursor is inside hour 3
    assert [int(row["start"].timestamp()) for row in rows] == [0, HOUR, 2 * HOUR]
    assert [row["sum"] for row in rows] == [0.0, 0.2, 0.5]
    assert [row["state"] for row in rows] == [0.1, 0.3, 0.6]   # counter at the end of each hour


def test_build_rows_needs_baseline_plus_one_hour():
    assert build_rows({}, cursor=10 * HOUR) == []
    assert build_rows({0: 5.0}, cursor=10 * HOUR) == []
    assert build_rows({0: 5.0, HOUR: 5.0}, cursor=HOUR + 10) == []   # only hour 0 is complete


async def test_backfill_is_imported_as_hourly_statistics(recorder_mock, hass, enable_custom_integrations, fake_shelly):
    now, clock = fixed_clock()
    first_hour = now // HOUR * HOUR - 5 * HOUR
    fake_shelly.page_size = 1000   # the whole backfill in a single update
    fill(fake_shelly, ((now - 5 * HOUR) // 60) * 60, 300)
    with clock:
        entry = await setup_entry(hass, fake_shelly, backfill_hours=5)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED

    expected = hourly_expected(fake_shelly.records, ((now - 5 * HOUR) // 60) * 60)
    current_hour = now // HOUR * HOUR   # the cursor's hour is left to the recorder
    complete = [hour for hour in sorted(expected) if hour < current_hour]
    assert len(complete) == 5

    for entity_id, index in ((IMPORT_ENTITY, 0), (EXPORT_ENTITY, 1)):
        rows = await read_statistics(hass, entity_id, first_hour)
        assert [row_start(row) for row in rows] == complete
        running = 0.0
        for position, (hour, row) in enumerate(zip(complete, rows)):
            running += expected[hour][index] / 1000
            assert row["state"] == pytest.approx(running, abs=1e-6)
            assert row["sum"] == pytest.approx(running - expected[complete[0]][index] / 1000, abs=1e-6)
        assert rows[0]["sum"] == 0
        # The live sensor continues exactly where the imported rows end.
        live = float(hass.states.get(entity_id).state)
        assert live - rows[-1]["state"] == pytest.approx(expected[current_hour][index] / 1000, abs=1e-6)

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.state["history_pending"] is False
    assert coordinator.state["hourly"] == {}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_existing_statistics_are_not_overwritten(recorder_mock, hass, enable_custom_integrations, fake_shelly, caplog):
    now, clock = fixed_clock()
    first_hour = now // HOUR * HOUR - 5 * HOUR
    fake_shelly.page_size = 1000   # the whole backfill in a single update
    fill(fake_shelly, ((now - 5 * HOUR) // 60) * 60, 300)
    async_import_statistics(
        hass,
        {
            "mean_type": StatisticMeanType.NONE, "has_sum": True, "name": None,
            "source": "recorder", "statistic_id": IMPORT_ENTITY, "unit_class": "energy",
            "unit_of_measurement": "kWh",
        },
        [{"start": datetime.fromtimestamp(first_hour - HOUR, timezone.utc), "state": 1.0, "sum": 0.5}],
    )
    await async_wait_recording_done(hass)
    with clock, caplog.at_level(logging.WARNING):
        entry = await setup_entry(hass, fake_shelly, backfill_hours=5)
    await hass.async_block_till_done(wait_background_tasks=True)

    rows = await read_statistics(hass, IMPORT_ENTITY, first_hour - 2 * HOUR)
    assert [(row_start(row), row["sum"]) for row in rows] == [(first_hour - HOUR, 0.5)]
    assert "already has long-term statistics" in caplog.text
    # the sensor without statistics still gets its history
    assert len(await read_statistics(hass, EXPORT_ENTITY, first_hour)) == 5
    await hass.config_entries.async_unload(entry.entry_id)


async def test_no_history_import_without_backfill(recorder_mock, hass, enable_custom_integrations, fake_shelly):
    now, clock = fixed_clock()
    fake_shelly.page_size = 1000
    fill(fake_shelly, ((now - 3 * HOUR) // 60) * 60, 180)
    with clock:
        entry = await setup_entry(hass, fake_shelly, backfill_hours=0)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.data[DOMAIN][entry.entry_id].state["history_pending"] is False
    assert await read_statistics(hass, IMPORT_ENTITY, now - 10 * HOUR) == []
    await hass.config_entries.async_unload(entry.entry_id)


async def test_existing_installation_gets_no_history_import(recorder_mock, hass, enable_custom_integrations, fake_shelly, hass_storage):
    now, _ = fixed_clock()
    fake_shelly.page_size = 1000
    fill(fake_shelly, ((now - 3 * HOUR) // 60) * 60, 180)
    entry = MockConfigEntry(
        domain=DOMAIN, title="Test", unique_id="aabbccddeeff", entry_id="existing",
        data={"host": fake_shelly.host, "name": "Test", "username": "admin",
              "password": fake_shelly.password, "backfill_hours": 3},
    )
    # State written by a version that did not know the history keys.
    hass_storage[f"{DOMAIN}.existing"] = {
        "version": 1, "minor_version": 1, "key": f"{DOMAIN}.existing",
        "data": {"import_wh": 0.0, "export_wh": 0.0, "cursor": ((now - 3 * HOUR) // 60) * 60,
                 "last_record_ts": None, "catch_up_pending": False},
    }
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert await read_statistics(hass, IMPORT_ENTITY, now - 10 * HOUR) == []
    await hass.config_entries.async_unload(entry.entry_id)


async def test_history_is_imported_after_a_staged_backfill(recorder_mock, hass, enable_custom_integrations, fake_shelly):
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    now, clock = fixed_clock()
    first_hour = now // HOUR * HOUR - 5 * HOUR
    fill(fake_shelly, ((now - 5 * HOUR) // 60) * 60, 300)   # 100 pages of 3 records: several updates
    with clock:
        entry = await setup_entry(hass, fake_shelly, backfill_hours=5)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.state["catch_up_pending"] is True
    assert await read_statistics(hass, IMPORT_ENTITY, first_hour) == []   # nothing before the end

    for _ in range(10):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
        await hass.async_block_till_done(wait_background_tasks=True)
        if not coordinator.state["history_pending"]:
            break
    assert coordinator.state["history_pending"] is False

    expected = hourly_expected(fake_shelly.records, ((now - 5 * HOUR) // 60) * 60)
    complete = [hour for hour in sorted(expected) if hour < now // HOUR * HOUR]
    rows = await read_statistics(hass, IMPORT_ENTITY, first_hour)
    assert [row_start(row) for row in rows] == complete
    await hass.config_entries.async_unload(entry.entry_id)
