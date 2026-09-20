from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        EnergySensor(coordinator, entry, "import_wh", "net_import", "import"),
        EnergySensor(coordinator, entry, "export_wh", "net_export", "export"),
        LastRecordSensor(coordinator, entry),
    ])


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


class BaseSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, suffix):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name=entry.title,
            manufacturer="Shelly",
            model="Pro 3EM (Phase Netting)",
        )


class EnergySensor(BaseSensor):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator, entry, key, translation_key, suffix):
        super().__init__(coordinator, entry, suffix)
        self.key = key
        self._attr_translation_key = translation_key

    @property
    def available(self) -> bool:
        # While the backlog is still being caught up (notably the initial backfill) the total is
        # incomplete. Staying unavailable makes the first valid value the statistics baseline, so
        # the backfilled energy is not booked as consumption in the first hour. The sensors also
        # wait for the statistics import: its anchor row must exist before the recorder sees the
        # first valid state, otherwise a 5-minute run in between would start an unanchored sum.
        return (
            super().available
            and not self.coordinator.data["catch_up_pending"]
            and not self.coordinator.history_pending
        )

    @property
    def native_value(self):
        return round(float(self.coordinator.data[self.key]) / 1000, 6)


class LastRecordSensor(BaseSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_record"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_record")

    @property
    def native_value(self):
        ts = self.coordinator.data.get("last_record_ts")
        return datetime.fromtimestamp(ts, timezone.utc) if ts is not None else None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        last_gap = data.get("last_gap")
        return {
            "cursor": data.get("cursor"),
            "catch_up_pending": data.get("catch_up_pending", False),
            "gaps": data.get("gap_count", 0),
            "missing_minutes": data.get("gap_minutes", 0),
            "last_gap_start": _iso(last_gap[0]) if last_gap else None,
            "last_gap_end": _iso(last_gap[1]) if last_gap else None,
            "clock_offset_seconds": data.get("clock_offset"),
        }
