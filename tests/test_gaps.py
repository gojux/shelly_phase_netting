import time

import pytest
from homeassistant.helpers import issue_registry as ir

from custom_components.shelly_phase_netting.const import DOMAIN, gap_issue_id

from .test_integration import fill, setup_entry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")

LAST_RECORD = "sensor.test_last_processed_record"


def start_of_window(minutes_back):
    return ((int(time.time()) - minutes_back * 60) // 60) * 60


def issue_of(hass, entry):
    return ir.async_get(hass).async_get_issue(DOMAIN, gap_issue_id(entry.entry_id))


async def test_a_long_gap_is_counted_and_raises_a_repair_notice(hass, fake_shelly):
    fake_shelly.page_size = 1000
    start = start_of_window(50)
    fill(fake_shelly, start, 5)                 # minutes 0-4
    fill(fake_shelly, start + 35 * 60, 5)       # minutes 35-39: 30 minutes without data in between
    entry = await setup_entry(hass, fake_shelly, backfill_hours=1)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    assert coordinator.state["gap_minutes"] == 30
    assert coordinator.state["gap_count"] == 1
    assert coordinator.state["last_gap"] == [start + 5 * 60, start + 35 * 60]
    attributes = hass.states.get(LAST_RECORD).attributes
    assert attributes["gaps"] == 1 and attributes["missing_minutes"] == 30
    assert attributes["last_gap_start"].startswith("20") and attributes["last_gap_end"] > attributes["last_gap_start"]

    issue = issue_of(hass, entry)
    assert issue is not None and issue.translation_key == "data_gap"
    assert issue.translation_placeholders["minutes"] == "30"
    assert issue.translation_placeholders["total"] == "30"
    assert issue.is_fixable is False
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_short_gap_is_counted_without_a_repair_notice(hass, fake_shelly):
    fake_shelly.page_size = 1000
    start = start_of_window(50)
    fill(fake_shelly, start, 5)
    fill(fake_shelly, start + 10 * 60, 5)       # 5 minutes missing
    entry = await setup_entry(hass, fake_shelly, backfill_hours=1)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert (coordinator.state["gap_minutes"], coordinator.state["gap_count"]) == (5, 1)
    assert issue_of(hass, entry) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_contiguous_records_have_no_gap(hass, fake_shelly):
    fake_shelly.page_size = 1000
    fill(fake_shelly, start_of_window(50), 40)
    entry = await setup_entry(hass, fake_shelly, backfill_hours=1)
    attributes = hass.states.get(LAST_RECORD).attributes
    assert (attributes["gaps"], attributes["missing_minutes"]) == (0, 0)
    assert attributes["last_gap_start"] is None and attributes["last_gap_end"] is None
    assert issue_of(hass, entry) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_history_that_starts_later_than_requested_is_not_a_gap(hass, fake_shelly):
    fake_shelly.page_size = 1000
    fill(fake_shelly, start_of_window(30), 20)   # the Shelly only has the last half hour ...
    entry = await setup_entry(hass, fake_shelly, backfill_hours=3)   # ... but 3 hours were requested
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.state["gap_minutes"] == 0
    assert issue_of(hass, entry) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_gap_that_appears_while_running_is_added_up(hass, fake_shelly):
    fake_shelly.page_size = 1000
    start = start_of_window(50)
    fill(fake_shelly, start, 10)
    entry = await setup_entry(hass, fake_shelly, backfill_hours=1)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.state["gap_count"] == 0

    fill(fake_shelly, start + 40 * 60, 3)       # the Shelly was off for 30 minutes
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert (coordinator.state["gap_minutes"], coordinator.state["gap_count"]) == (30, 1)
    assert issue_of(hass, entry).translation_placeholders["minutes"] == "30"

    fill(fake_shelly, start + 50 * 60, 3)       # another 7 minutes without records
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert (coordinator.state["gap_minutes"], coordinator.state["gap_count"]) == (37, 2)
    # the notice keeps describing the last long gap and shows the totals
    assert issue_of(hass, entry).translation_placeholders["total"] == "30"   # the 7 minute gap is short
    await hass.config_entries.async_unload(entry.entry_id)


async def test_removing_the_integration_removes_the_repair_notice(hass, fake_shelly):
    fake_shelly.page_size = 1000
    start = start_of_window(50)
    fill(fake_shelly, start, 5)
    fill(fake_shelly, start + 35 * 60, 5)
    entry = await setup_entry(hass, fake_shelly, backfill_hours=1)
    assert issue_of(hass, entry) is not None
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, gap_issue_id(entry.entry_id)) is None
