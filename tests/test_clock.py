import time

import pytest
from homeassistant.helpers import issue_registry as ir

from custom_components.shelly_phase_netting.const import DOMAIN, clock_issue_id

from .test_integration import fill, setup_entry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")

LAST_RECORD = "sensor.test_last_processed_record"


def issue_of(hass, entry):
    return ir.async_get(hass).async_get_issue(DOMAIN, clock_issue_id(entry.entry_id))


def clock_requests(fake_shelly):
    return [path for path, _ in fake_shelly.requests if path == "/rpc/Sys.GetStatus"]


async def test_a_correct_clock_raises_nothing(hass, fake_shelly):
    entry = await setup_entry(hass, fake_shelly, backfill_hours=0)
    assert issue_of(hass, entry) is None
    assert abs(hass.states.get(LAST_RECORD).attributes["clock_offset_seconds"]) <= 2
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_clock_that_is_off_raises_a_repair_notice(hass, fake_shelly):
    fake_shelly.clock_offset = 600   # ten minutes ahead
    entry = await setup_entry(hass, fake_shelly, backfill_hours=0)
    issue = issue_of(hass, entry)
    assert issue is not None and issue.translation_key == "clock_offset"
    assert issue.translation_placeholders["minutes"] == "10"
    assert issue.is_fixable is False
    assert 598 <= hass.states.get(LAST_RECORD).attributes["clock_offset_seconds"] <= 602
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_small_difference_is_tolerated(hass, fake_shelly):
    fake_shelly.clock_offset = -90   # within the two minute tolerance
    entry = await setup_entry(hass, fake_shelly, backfill_hours=0)
    assert issue_of(hass, entry) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_shelly_without_a_valid_time_raises_a_repair_notice(hass, fake_shelly):
    fake_shelly.clock_offset = None
    entry = await setup_entry(hass, fake_shelly, backfill_hours=0)
    issue = issue_of(hass, entry)
    assert issue is not None and issue.translation_key == "clock_not_set"
    assert hass.states.get(LAST_RECORD).attributes["clock_offset_seconds"] is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_notice_disappears_once_the_clock_is_right(hass, fake_shelly):
    fake_shelly.clock_offset = 600
    entry = await setup_entry(hass, fake_shelly, backfill_hours=0)
    assert issue_of(hass, entry) is not None
    coordinator = hass.data[DOMAIN][entry.entry_id]

    fake_shelly.clock_offset = 0
    coordinator._next_clock_check = 0   # the hourly check is due
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert issue_of(hass, entry) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_clock_is_only_read_now_and_then(hass, fake_shelly):
    fill(fake_shelly, ((int(time.time()) - 1800) // 60) * 60, 3)
    entry = await setup_entry(hass, fake_shelly, backfill_hours=1)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    for _ in range(4):
        await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(clock_requests(fake_shelly)) == 1   # one extra request per hour, not per poll
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_failing_clock_check_does_not_fail_the_poll(hass, fake_shelly):
    fake_shelly.clock_available = False   # no Sys.GetStatus on this device
    entry = await setup_entry(hass, fake_shelly, backfill_hours=0)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.last_update_success is True
    assert issue_of(hass, entry) is None
    assert hass.states.get(LAST_RECORD).attributes["clock_offset_seconds"] is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_removing_the_integration_removes_the_notice(hass, fake_shelly):
    fake_shelly.clock_offset = 600
    entry = await setup_entry(hass, fake_shelly, backfill_hours=0)
    assert issue_of(hass, entry) is not None
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, clock_issue_id(entry.entry_id)) is None
