DOMAIN = "shelly_phase_netting"
PLATFORMS = ["sensor"]
DEFAULT_NAME = "Shelly Phase Netting"
CONF_BACKFILL_HOURS = "backfill_hours"
CONF_SCAN_INTERVAL = "scan_interval"
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


def store_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}"


def gap_issue_id(entry_id: str) -> str:
    return f"data_gap_{entry_id}"
