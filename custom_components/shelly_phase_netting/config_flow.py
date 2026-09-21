from __future__ import annotations

import logging
import time

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback

from .api import (
    SHELLY_USERNAME,
    ShellyApi,
    ShellyApiError,
    ShellyAuthError,
    ShellyNotSupportedError,
)
from .const import (
    CONF_BACKFILL_HOURS,
    DEFAULT_BACKFILL_HOURS,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_BACKFILL_HOURS,
)

_LOGGER = logging.getLogger(__name__)


async def _async_probe(hass, host, username, password) -> tuple[dict, str | None]:
    """Contact the Shelly; return (device info, error key or None)."""
    api = ShellyApi(host, username, password)
    try:
        info = await hass.async_add_executor_job(api.get_device_info)
        # EMData only exists in the triphase profile of the Pro 3EM.
        await hass.async_add_executor_job(api.get_data, int(time.time()))
    except ShellyAuthError:
        return {}, "invalid_auth"
    except ShellyNotSupportedError:
        return {}, "emdata_unavailable"
    except ShellyApiError:
        return {}, "cannot_connect"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error while testing the connection")
        return {}, "unknown"
    finally:
        await hass.async_add_executor_job(api.close)
    return info, None


class ShellyPhaseNettingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            info, error = await _async_probe(
                self.hass,
                user_input[CONF_HOST],
                user_input.get(CONF_USERNAME),
                user_input.get(CONF_PASSWORD),
            )
            if error is None:
                mac = str(info.get("mac", user_input[CONF_HOST])).lower()
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
            errors["base"] = error

        schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
            vol.Optional(CONF_USERNAME, default=SHELLY_USERNAME): str,
            vol.Optional(CONF_PASSWORD): str,
            vol.Required(CONF_BACKFILL_HOURS, default=DEFAULT_BACKFILL_HOURS): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=MAX_BACKFILL_HOURS)
            ),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            _, error = await _async_probe(
                self.hass,
                entry.data[CONF_HOST],
                user_input.get(CONF_USERNAME),
                user_input.get(CONF_PASSWORD),
            )
            if error is None:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
            errors["base"] = error

        schema = vol.Schema({
            vol.Optional(
                CONF_USERNAME, default=entry.data.get(CONF_USERNAME, SHELLY_USERNAME)
            ): str,
            vol.Required(CONF_PASSWORD): str,
        })
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    async def async_step_reconfigure(self, user_input=None):
        """Change the address or the credentials of an already configured Shelly."""
        errors = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            # An empty field keeps the stored value, so the password does not have to be re-entered.
            username = user_input.get(CONF_USERNAME) or entry.data.get(CONF_USERNAME)
            password = user_input.get(CONF_PASSWORD) or entry.data.get(CONF_PASSWORD)
            info, error = await _async_probe(self.hass, user_input[CONF_HOST], username, password)
            if error is None and str(info.get("mac", entry.unique_id)).lower() != entry.unique_id:
                error = "wrong_device"
            if error is None:
                updates = {CONF_HOST: user_input[CONF_HOST]}
                if username:
                    updates[CONF_USERNAME] = username
                if password:
                    updates[CONF_PASSWORD] = password
                return self.async_update_reload_and_abort(entry, data_updates=updates)
            errors["base"] = error

        current = user_input or entry.data
        schema = vol.Schema({
            vol.Required(CONF_HOST, default=current.get(CONF_HOST, "")): str,
            vol.Optional(CONF_USERNAME, default=current.get(CONF_USERNAME) or SHELLY_USERNAME): str,
            vol.Optional(CONF_PASSWORD): str,
        })
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600))
            }),
        )
