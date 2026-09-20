"""Diagnostics download for bug reports (host, credentials and device ids are redacted)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .api import ShellyApiError
from .const import DOMAIN

TO_REDACT = {CONF_HOST, CONF_PASSWORD, CONF_USERNAME, "unique_id", "mac", "id", "name", "ssid"}


def _iso(timestamp: int | None) -> str | None:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if timestamp else None


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    state = coordinator.state
    hourly = state["hourly"]

    try:
        device = await hass.async_add_executor_job(coordinator.api.get_device_info)
    except ShellyApiError as err:
        device = {"error": str(err)}

    return async_redact_data(
        {
            "entry": {
                "version": entry.version,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            "device": device,
            "coordinator": {
                "last_update_success": coordinator.last_update_success,
                "last_exception": repr(coordinator.last_exception) if coordinator.last_exception else None,
                "update_interval_seconds": coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None,
            },
            "state": {
                "import_wh": state["import_wh"],
                "export_wh": state["export_wh"],
                "cursor": _iso(state["cursor"]),
                "last_record": _iso(state["last_record_ts"]),
                "catch_up_pending": state["catch_up_pending"],
                "history_pending": state["history_pending"],
                "history_hours_collected": len(hourly),
                "gaps": state["gap_count"],
                "missing_minutes": state["gap_minutes"],
                "last_gap": [_iso(state["last_gap"][0]), _iso(state["last_gap"][1])]
                if state["last_gap"]
                else None,
            },
        },
        TO_REDACT,
    )
