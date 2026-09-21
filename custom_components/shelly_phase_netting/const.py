from homeassistant.const import Platform

DOMAIN = "shelly_phase_netting"
PLATFORMS = [Platform.SENSOR]
DEFAULT_NAME = "Shelly Phase Netting"
CONF_BACKFILL_HOURS = "backfill_hours"
DEFAULT_SCAN_INTERVAL = 60
DEFAULT_BACKFILL_HOURS = 24
MAX_BACKFILL_HOURS = 45 * 24
STORE_VERSION = 1
# A single update fetches at most this many pages from the Shelly. Larger backlogs
# (e.g. the initial backfill) are worked off by follow-up updates so that setup
# does not have to wait for them.
MAX_PAGES_PER_UPDATE = 20
CATCH_UP_INTERVAL = 2
# A gap of at least this many minutes in the Shelly's history raises a repair notice.
GAP_ISSUE_MINUTES = 10
# The Shelly's clock is compared with Home Assistant's at start and then this often (seconds).
CLOCK_CHECK_INTERVAL = 3600
# Beyond this difference (seconds) the records would be assigned to the wrong hours.
CLOCK_TOLERANCE = 120


def store_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}"


def gap_issue_id(entry_id: str) -> str:
    return f"data_gap_{entry_id}"


def clock_issue_id(entry_id: str) -> str:
    return f"clock_{entry_id}"
