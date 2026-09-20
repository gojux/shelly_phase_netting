import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType

from custom_components.shelly_phase_netting.const import DOMAIN

from .test_integration import setup_entry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")


async def test_reconfigure_moves_the_integration_to_a_new_address(hass, fake_shelly, fake_shelly_factory):
    entry = await setup_entry(hass, fake_shelly)
    moved = fake_shelly_factory()   # same device (same MAC and password), reachable under a new address
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "reconfigure"

    # The password field is left empty: the stored password is kept.
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": moved.host})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    assert entry.data["host"] == moved.host
    assert entry.data["password"] == "secret"
    assert entry.state is ConfigEntryState.LOADED
    assert hass.data[DOMAIN][entry.entry_id].api.host == moved.host
    assert any(path == "/rpc/EMData.GetData" for path, _ in moved.requests)   # polled at the new address
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_can_change_the_password(hass, fake_shelly, fake_shelly_factory):
    entry = await setup_entry(hass, fake_shelly)
    moved = fake_shelly_factory(password="new-secret")
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": moved.host, "password": "new-secret"}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data["password"] == "new-secret"
    assert entry.state is ConfigEntryState.LOADED
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("kwargs", "form", "error"),
    [
        ({"mac": "112233445566"}, {}, "wrong_device"),            # another device at that address
        ({}, {"password": "wrong"}, "invalid_auth"),
        ({"emdata": False}, {}, "emdata_unavailable"),
    ],
)
async def test_reconfigure_reports_problems_and_keeps_the_entry(
    hass, fake_shelly, fake_shelly_factory, kwargs, form, error
):
    entry = await setup_entry(hass, fake_shelly)
    other = fake_shelly_factory(**kwargs)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": other.host, **form})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": error}
    assert entry.data["host"] == fake_shelly.host   # unchanged
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_reports_an_unreachable_address(hass, fake_shelly):
    entry = await setup_entry(hass, fake_shelly)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "127.0.0.1:1"})
    assert result["errors"] == {"base": "cannot_connect"}
    await hass.config_entries.async_unload(entry.entry_id)
