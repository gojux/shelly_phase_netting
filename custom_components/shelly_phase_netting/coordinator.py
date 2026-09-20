from __future__ import annotations

from datetime import timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ShellyApi, ShellyApiError, ShellyAuthError
from .const import (
    CATCH_UP_INTERVAL,
    CONF_BACKFILL_HOURS,
    CONF_SCAN_INTERVAL,
    DEFAULT_BACKFILL_HOURS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    GAP_ISSUE_MINUTES,
    MAX_PAGES_PER_UPDATE,
    STORE_VERSION,
    gap_issue_id,
    store_key,
)
from .history import async_import_history

_LOGGER = logging.getLogger(__name__)
ENERGY_KEYS = (
    "a_total_act_energy", "a_total_act_ret_energy",
    "b_total_act_energy", "b_total_act_ret_energy",
    "c_total_act_energy", "c_total_act_ret_energy",
)


def _local_time(timestamp: int) -> str:
    return dt_util.as_local(dt_util.utc_from_timestamp(timestamp)).strftime("%Y-%m-%d %H:%M")


class ShellyPhaseNettingCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._poll_interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._poll_interval,
        )
        self.api = ShellyApi(
            entry.data[CONF_HOST], entry.data.get(CONF_USERNAME), entry.data.get(CONF_PASSWORD)
        )
        self.store = Store(hass, STORE_VERSION, store_key(entry.entry_id))
        self.state = {
            "import_wh": 0.0,
            "export_wh": 0.0,
            "cursor": None,
            "last_record_ts": None,
            "catch_up_pending": False,
            # Initial backfill only: energy per hour until it has been written to the recorder.
            "history_pending": False,
            "hourly": {},
            # Hour in which the initial backfill completed, and the start of the 5-minute slot
            # before it completed: where the recorder's running sum is anchored.
            "history_cursor_hour": None,
            "history_anchor_ts": None,
            # Gaps in the Shelly's history: minutes without data that were skipped.
            "gap_minutes": 0,
            "gap_count": 0,
            "last_gap": None,   # [start, end] as timestamps
        }
        self._history_task = None

    async def async_initialize(self) -> None:
        saved = await self.store.async_load()
        if saved:
            self.state.update({key: saved[key] for key in self.state if key in saved})
        else:
            now = int(time.time())
            hours = self.config_entry.data.get(CONF_BACKFILL_HOURS, DEFAULT_BACKFILL_HOURS)
            self.state["cursor"] = ((now - hours * 3600) // 60) * 60
            self.state["history_pending"] = hours > 0
        await self.async_config_entry_first_refresh()

    async def _async_update_data(self):
        cursor = int(self.state["cursor"])
        original_cursor = cursor
        import_wh = float(self.state["import_wh"])
        export_wh = float(self.state["export_wh"])
        last_record_ts = self.state["last_record_ts"]
        history = self.state["history_pending"]
        hourly = {hour: list(values) for hour, values in self.state["hourly"].items()}
        gaps: list[tuple[int, int]] = []
        pages = 0
        pending = False
        try:
            while True:
                if pages >= MAX_PAGES_PER_UPDATE:
                    # The Shelly announced more records; a quick follow-up update continues.
                    pending = True
                    break
                page_start = cursor
                payload = await self.hass.async_add_executor_job(self.api.get_data, cursor)
                keys = payload.get("keys", [])
                missing = [key for key in ENERGY_KEYS if key not in keys]
                if missing:
                    raise UpdateFailed(
                        "Shelly response lacks the expected energy fields: "
                        + ", ".join(missing)
                    )
                indices = [keys.index(key) for key in ENERGY_KEYS]
                advanced = False
                for block in payload.get("data", []):
                    ts = int(block["ts"])
                    period = int(block.get("period", 60))
                    for offset, row in enumerate(block.get("values", [])):
                        record_ts = ts + offset * period
                        if record_ts < cursor:
                            continue
                        if last_record_ts is not None and record_ts > last_record_ts + period:
                            # Minutes the Shelly has no record for (it was off, or its history
                            # was overwritten): their energy cannot be recovered.
                            gaps.append((last_record_ts + period, record_ts))
                        net_wh = sum(
                            float(row[indices[i]]) - float(row[indices[i + 1]])
                            for i in (0, 2, 4)
                        )
                        if net_wh >= 0:
                            import_wh += net_wh
                        else:
                            export_wh += -net_wh
                        if history:
                            bucket = hourly.setdefault(str(record_ts // 3600 * 3600), [0.0, 0.0])
                            bucket[0 if net_wh >= 0 else 1] += abs(net_wh)
                        last_record_ts = record_ts
                        cursor = record_ts + period
                        advanced = True
                next_ts = payload.get("next_record_ts")
                if next_ts is None:
                    break
                next_ts = int(next_ts)
                if next_ts <= page_start:
                    break
                cursor = max(cursor, next_ts)
                pages += 1
                if not advanced and cursor <= page_start:
                    break
            self.state["import_wh"] = import_wh
            self.state["export_wh"] = export_wh
            self.state["last_record_ts"] = last_record_ts
            self.state["cursor"] = cursor
            self.state["catch_up_pending"] = pending
            self.state["hourly"] = hourly
            for gap_start, gap_end in gaps:
                self.state["gap_minutes"] += (gap_end - gap_start) // 60
                self.state["gap_count"] += 1
                self.state["last_gap"] = [gap_start, gap_end]
            if history and not pending and self.state["history_cursor_hour"] is None:
                self.state["history_cursor_hour"] = cursor // 3600 * 3600
                self.state["history_anchor_ts"] = int(time.time()) // 300 * 300 - 300
            if cursor != original_cursor:
                await self.store.async_save(self.state)
            self._report_gaps(gaps)
            self.update_interval = (
                timedelta(seconds=CATCH_UP_INTERVAL) if pending else self._poll_interval
            )
            return dict(self.state)
        except ShellyAuthError as err:
            self.update_interval = self._poll_interval
            raise ConfigEntryAuthFailed(f"Shelly rejected the credentials: {err}") from err
        except ShellyApiError as err:
            self.update_interval = self._poll_interval
            raise UpdateFailed(f"Shelly request failed: {err}") from err

    def _report_gaps(self, gaps: list[tuple[int, int]]) -> None:
        """Log new gaps and keep one repair notice about the long ones."""
        for gap_start, gap_end in gaps:
            minutes = (gap_end - gap_start) // 60
            _LOGGER.log(
                logging.WARNING if minutes >= GAP_ISSUE_MINUTES else logging.INFO,
                "The Shelly has no data for %d minutes (from %s to %s); their energy is missing "
                "from the totals",
                minutes,
                _local_time(gap_start),
                _local_time(gap_end),
            )
        long_gaps = [gap for gap in gaps if (gap[1] - gap[0]) // 60 >= GAP_ISSUE_MINUTES]
        if not long_gaps:
            return
        gap_start, gap_end = long_gaps[-1]
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            gap_issue_id(self.config_entry.entry_id),
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="data_gap",
            translation_placeholders={
                "name": self.config_entry.title,
                "minutes": str((gap_end - gap_start) // 60),
                "start": _local_time(gap_start),
                "end": _local_time(gap_end),
                "total": str(self.state["gap_minutes"]),
                "count": str(self.state["gap_count"]),
            },
        )

    @property
    def history_pending(self) -> bool:
        """True until the initial statistics import has been handled."""
        return bool(self.state["history_pending"])

    @callback
    def async_schedule_history_import(self) -> None:
        """Start the one-time statistics import as soon as the initial backfill is complete."""
        if (
            not self.state["history_pending"]
            or self.state["catch_up_pending"]
            or self.state["history_cursor_hour"] is None
            or self.state["history_anchor_ts"] is None
            or self._history_task is not None
        ):
            return
        self._history_task = self.config_entry.async_create_background_task(
            self.hass, self._async_import_history(), name=f"{DOMAIN} history import"
        )

    async def _async_import_history(self) -> None:
        try:
            finished = await async_import_history(
                self.hass,
                self.config_entry,
                dict(self.state["hourly"]),
                int(self.state["history_cursor_hour"]),
                int(self.state["history_anchor_ts"]),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Importing the backfilled history failed; skipping it")
            finished = True
        finally:
            self._history_task = None
        if finished:
            self.state["history_pending"] = False
            self.state["hourly"] = {}
            self.state["history_cursor_hour"] = None
            self.state["history_anchor_ts"] = None
            await self.store.async_save(self.state)
            # The energy sensors were held back until now; let them publish their first value.
            self.async_update_listeners()
