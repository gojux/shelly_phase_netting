"""Write the hourly history of the initial backfill into the recorder's long-term statistics."""
from __future__ import annotations

from datetime import datetime, timezone
import logging

from homeassistant.components.recorder import DOMAIN as RECORDER_DOMAIN, get_instance
from homeassistant.components.recorder.db_schema import StatisticsShortTerm
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_conversion import EnergyConverter

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
HOUR = 3600
# Index of each sensor's energy in the [import_wh, export_wh] pair stored per hour.
SENSORS = {"import": 0, "export": 1}


def build_rows(energy_wh_per_hour: dict[int, float], cursor_hour: int) -> list[StatisticData]:
    """Turn the energy per hour (Wh) into cumulative hourly statistics rows.

    The first hour only serves as the baseline (sum 0, state = counter at its end), like the
    first row the recorder writes itself. The hour containing the cursor (`cursor_hour`) and
    everything after it is left to the recorder, which compiles it from the live sensor states.
    """
    hours = sorted(hour for hour in energy_wh_per_hour if hour < cursor_hour)
    if len(hours) < 2:
        return []
    rows: list[StatisticData] = []
    total_wh = 0.0
    sum_wh = 0.0
    for index, hour in enumerate(hours):
        total_wh += energy_wh_per_hour[hour]
        if index:
            sum_wh += energy_wh_per_hour[hour]
        rows.append(
            StatisticData(
                start=datetime.fromtimestamp(hour, timezone.utc),
                state=round(total_wh / 1000, 6),
                sum=round(sum_wh / 1000, 6),
            )
        )
    return rows


def async_import_series(
    hass: HomeAssistant, entity_id: str, rows: list[StatisticData], anchor_ts: int
) -> None:
    """Import the hourly rows and anchor the recorder's own statistics at their end.

    The recorder computes new hourly values from its 5-minute statistics, whose running sum
    continues from the latest 5-minute row of the entity. Without such a row it starts again at
    0 with the first valid state, which would make the sum jump back by the imported total. One
    5-minute row (`anchor_ts`, the start of a slot before the first valid state), carrying the
    state and sum of the last hourly row, lets the recorder continue exactly there; the energy
    counted before the sensor became valid is then booked as well. The sensors must not have a
    valid state yet, otherwise a 5-minute run in between would start its own chain.
    """
    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=None,
        source=RECORDER_DOMAIN,
        statistic_id=entity_id,
        unit_class=EnergyConverter.UNIT_CLASS,
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    )
    async_import_statistics(hass, metadata, rows)
    anchor = StatisticData(
        start=datetime.fromtimestamp(anchor_ts, timezone.utc),
        state=rows[-1]["state"],
        sum=rows[-1]["sum"],
    )
    get_instance(hass).async_import_statistics(metadata, [anchor], StatisticsShortTerm)


async def async_import_history(
    hass: HomeAssistant,
    entry: ConfigEntry,
    hourly: dict[str, list[float]],
    cursor_hour: int,
    anchor_ts: int,
) -> bool:
    """Import the hourly history for both energy sensors.

    `cursor_hour` is the hour in which the sensors became valid; it is left to the recorder.

    Returns True when finished (imported or deliberately skipped) and False when it has to be
    retried later because the sensors are not registered yet.
    """
    if RECORDER_DOMAIN not in hass.config.components:
        _LOGGER.debug("Recorder is not loaded, skipping the history import")
        return True

    registry = er.async_get(hass)
    entity_ids: dict[str, str] = {}
    for kind in SENSORS:
        entity_id = registry.async_get_entity_id(Platform.SENSOR, DOMAIN, f"{entry.unique_id}_{kind}")
        if entity_id is None:
            return False
        entity_ids[kind] = entity_id

    for kind, index in SENSORS.items():
        entity_id = entity_ids[kind]
        rows = build_rows({int(hour): values[index] for hour, values in hourly.items()}, cursor_hour)
        if not rows:
            continue
        existing = await get_instance(hass).async_add_executor_job(
            get_last_statistics, hass, 1, entity_id, True, {"sum"}
        )
        if existing.get(entity_id):
            # Importing over existing rows would break the running sum of the recorder.
            _LOGGER.warning(
                "%s already has long-term statistics; not importing the backfilled history. "
                "Delete its statistics and set the integration up again to get the history",
                entity_id,
            )
            continue
        async_import_series(hass, entity_id, rows, anchor_ts)
        _LOGGER.info(
            "Imported %d hourly statistics for %s (last sum %s kWh) and anchored the recorder's "
            "running sum at %s",
            len(rows),
            entity_id,
            rows[-1]["sum"],
            datetime.fromtimestamp(anchor_ts, timezone.utc).isoformat(),
        )
    return True
