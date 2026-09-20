import json

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from .test_integration import fill, setup_entry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")


async def test_diagnostics_show_the_state_and_hide_secrets(hass, hass_client, fake_shelly):
    import time

    assert await async_setup_component(hass, "diagnostics", {})
    fake_shelly.page_size = 1000
    fill(fake_shelly, ((int(time.time()) - 2000) // 60) * 60, 20)
    entry = await setup_entry(hass, fake_shelly, backfill_hours=1)

    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert result["device"]["ver"] == "2.0.0"                    # the firmware helps with bug reports
    assert result["device"]["model"] == "SPEM-003CEBEU"
    assert result["coordinator"]["last_update_success"] is True
    assert result["state"]["import_wh"] > 0 and result["state"]["cursor"] is not None
    assert result["state"]["gaps"] == 0
    dump = json.dumps(result)
    for secret in (fake_shelly.host, fake_shelly.host.split(":")[0], "secret", "aabbccddeeff", "AABBCCDDEEFF"):
        assert secret not in dump, secret
    assert result["entry"]["data"]["password"] == "**REDACTED**"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_diagnostics_survive_an_unreachable_shelly(hass, hass_client, fake_shelly):
    assert await async_setup_component(hass, "diagnostics", {})
    entry = await setup_entry(hass, fake_shelly, backfill_hours=0)
    fake_shelly.busy = 99   # the Shelly stays busy while the report is created
    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert "busy" in result["device"]["error"]
    fake_shelly.busy = 0
    await hass.config_entries.async_unload(entry.entry_id)
