import time
from unittest.mock import patch
import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.shelly_phase_netting.const import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")

def fill(fs, start, n):
    # per minute: phase A imports 10 Wh, B exports 4 Wh (net +6), and every 5th minute net negative
    for i in range(n):
        t = start + 60 * i
        fs.records[t] = (10, 0, 0, 4, 0, 0) if i % 5 else (0, 10, 0, 0, 0, 0)

async def setup_entry(hass, fs, backfill_hours=1, **kw):
    entry = MockConfigEntry(domain=DOMAIN, title="Test", unique_id="aabbccddeeff", data={
        "host": fs.host, "name": "Test", "username": "admin", "password": fs.password,
        "backfill_hours": backfill_hours}, **kw)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    # the statistics import runs as a background task and releases the energy sensors
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry

async def test_setup_backfill_paging(hass, fake_shelly):
    now = int(time.time()); start = ((now - 3600) // 60) * 60
    fill(fake_shelly, start, 10)   # 10 records, page size 3 -> 4 pages
    entry = await setup_entry(hass, fake_shelly)
    assert entry.state is ConfigEntryState.LOADED
    imp = hass.states.get("sensor.test_netted_grid_import")
    assert imp.attributes["friendly_name"] == "Test Netted grid import"
    exp = hass.states.get("sensor.test_netted_grid_export")
    # i%5==0 -> i=0,5: net -10 (export) ; others 8 records net +6 (import)
    assert float(imp.state) == pytest.approx(8 * 6 / 1000)
    assert float(exp.state) == pytest.approx(2 * 10 / 1000)
    last = hass.states.get("sensor.test_last_processed_record")
    assert last.attributes["cursor"] == start + 60 * 10
    # second refresh doesn't double count
    coord = hass.data[DOMAIN][entry.entry_id]
    await coord.async_refresh()
    assert float(hass.states.get("sensor.test_netted_grid_import").state) == pytest.approx(0.048)

async def test_auth_failure_starts_reauth(hass, fake_shelly):
    fake_shelly.password = "other"
    entry = MockConfigEntry(domain=DOMAIN, title="Test", unique_id="aabbccddeeff", data={
        "host": fake_shelly.host, "name": "Test", "username": "admin", "password": "wrong", "backfill_hours": 1})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"]["source"] == "reauth" for f in flows)
    # complete reauth with right password
    flow = next(f for f in flows if f["context"]["source"] == "reauth")
    res = await hass.config_entries.flow.async_configure(flow["flow_id"], {"username": "admin", "password": "bad"})
    assert res["errors"] == {"base": "invalid_auth"}
    res = await hass.config_entries.flow.async_configure(flow["flow_id"], {"username": "admin", "password": "other"})
    assert res["type"] is FlowResultType.ABORT and res["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data["password"] == "other"
    assert entry.state is ConfigEntryState.LOADED
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

async def test_user_flow(hass, fake_shelly):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    base = {"host": fake_shelly.host, "name": "Neu", "username": "admin", "backfill_hours": 0}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {**base, "password": "nope"})
    assert r["errors"] == {"base": "invalid_auth"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {**base, "password": "secret"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

async def test_user_flow_monophase(hass, fake_shelly):
    fake_shelly.emdata = False
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"host": fake_shelly.host, "name": "N", "username": "admin", "password": "secret", "backfill_hours": 0})
    assert r["errors"] == {"base": "emdata_unavailable"}

async def test_user_flow_unreachable(hass):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"host": "127.0.0.1:1", "name": "N", "username": "admin", "backfill_hours": 0})
    assert r["errors"] == {"base": "cannot_connect"}

async def test_options_reload_applies_interval(hass, fake_shelly):
    entry = await setup_entry(hass, fake_shelly)
    coord = hass.data[DOMAIN][entry.entry_id]
    assert coord.update_interval.total_seconds() == 60
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"scan_interval": 120})
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id].update_interval.total_seconds() == 120
    assert entry.state is ConfigEntryState.LOADED

async def test_remove_deletes_store(hass, fake_shelly, hass_storage):
    now = int(time.time()); fill(fake_shelly, ((now - 3600)//60)*60, 4)
    entry = await setup_entry(hass, fake_shelly)
    key = f"{DOMAIN}.{entry.entry_id}"
    assert key in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage

async def test_restart_keeps_totals(hass, fake_shelly):
    now = int(time.time()); fill(fake_shelly, ((now - 3600)//60)*60, 6)
    entry = await setup_entry(hass, fake_shelly)
    before = hass.states.get("sensor.test_netted_grid_import").state
    await hass.config_entries.async_reload(entry.entry_id); await hass.async_block_till_done()
    assert hass.states.get("sensor.test_netted_grid_import").state == before

async def test_backfill_continues_in_background(hass, fake_shelly):
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    now = int(time.time()); start = ((now - 3600) // 60) * 60
    fill(fake_shelly, start, 10)   # page size 3 -> 4 pages; limit 2 pages per update
    seen_states = []
    hass.bus.async_listen(
        "state_changed",
        lambda event: seen_states.append(event.data["new_state"].state)
        if event.data["entity_id"] == "sensor.test_netted_grid_import" else None,
    )
    with patch("custom_components.shelly_phase_netting.coordinator.MAX_PAGES_PER_UPDATE", 2):
        entry = await setup_entry(hass, fake_shelly)
        # the incomplete total must not be exposed while the backlog is being caught up
        assert hass.states.get("sensor.test_netted_grid_import").state == "unavailable"
        assert hass.states.get("sensor.test_netted_grid_export").state == "unavailable"
        # setup returned after the first bounded update: partial result, catch-up pending
        last = hass.states.get("sensor.test_last_processed_record")
        assert entry.state is ConfigEntryState.LOADED
        assert last.attributes["catch_up_pending"] is True
        assert last.attributes["cursor"] < start + 60 * 10
        coord = hass.data[DOMAIN][entry.entry_id]
        assert coord.update_interval.total_seconds() == 2
        # follow-up updates finish the backlog without any further trigger
        for _ in range(5):
            async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
            await hass.async_block_till_done(wait_background_tasks=True)
            if not coord.data["catch_up_pending"]:
                break
    last = hass.states.get("sensor.test_last_processed_record")
    assert last.attributes["catch_up_pending"] is False
    assert last.attributes["cursor"] == start + 60 * 10
    assert float(hass.states.get("sensor.test_netted_grid_import").state) == pytest.approx(0.048)
    assert float(hass.states.get("sensor.test_netted_grid_export").state) == pytest.approx(0.02)
    assert coord.update_interval.total_seconds() == 60
    # the only value that was ever published is the complete one
    assert {state for state in seen_states if state != "unavailable"} == {"0.048"}


async def test_entity_names_are_translated_to_german(hass, fake_shelly):
    hass.config.language = "de"
    fill(fake_shelly, ((int(time.time()) - 3600) // 60) * 60, 2)
    await setup_entry(hass, fake_shelly)
    states = {state.attributes["friendly_name"] for state in hass.states.async_all("sensor")}
    assert states == {
        "Test Netzbezug saldiert",
        "Test Netzeinspeisung saldiert",
        "Test Letzter verarbeiteter Datensatz",
    }


async def test_last_record_sensor_is_a_diagnostic_entity(hass, fake_shelly):
    from homeassistant.const import EntityCategory
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="Test", unique_id="aabbccddeeff", data={
        "host": fake_shelly.host, "name": "Test", "username": "admin", "password": fake_shelly.password,
        "backfill_hours": 0})
    entry.add_to_hass(hass)
    # An installation from before the category existed: the sensor is already registered without one.
    registry.async_get_or_create(
        "sensor", DOMAIN, "aabbccddeeff_last_record", config_entry=entry, suggested_object_id="test_last_record"
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    by_unique_id = {item.unique_id: item for item in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert by_unique_id["aabbccddeeff_last_record"].entity_category is EntityCategory.DIAGNOSTIC
    assert by_unique_id["aabbccddeeff_import"].entity_category is None
    assert by_unique_id["aabbccddeeff_export"].entity_category is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_single_busy_answer_does_not_make_the_sensors_unavailable(hass, fake_shelly):
    fill(fake_shelly, ((int(time.time()) - 3600) // 60) * 60, 5)
    entry = await setup_entry(hass, fake_shelly)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entity_id = "sensor.test_netted_grid_import"
    assert hass.states.get(entity_id).state != "unavailable"

    fake_shelly.busy = 1   # one 429, the repeated request is answered
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success is True
    assert hass.states.get(entity_id).state != "unavailable"

    fake_shelly.busy = 3   # stays busy for all attempts: the poll fails, the next one recovers
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success is False
    assert hass.states.get(entity_id).state == "unavailable"
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success is True
    assert hass.states.get(entity_id).state != "unavailable"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_home_assistant_loads_the_sensor_icons(hass, enable_custom_integrations):
    from homeassistant.helpers.icon import async_get_icons

    icons = await async_get_icons(hass, "entity", [DOMAIN])
    sensors = icons[DOMAIN]["sensor"]
    # Grid import: power flows out of the tower towards the house; export: into the tower.
    assert sensors["net_import"]["default"] == "mdi:transmission-tower-export"
    assert sensors["net_export"]["default"] == "mdi:transmission-tower-import"
    assert sensors["last_record"]["default"] == "mdi:clock-check-outline"
