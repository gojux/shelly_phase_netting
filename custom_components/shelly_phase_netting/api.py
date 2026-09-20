from __future__ import annotations

from types import SimpleNamespace
import threading
import time

import requests
from requests.auth import HTTPDigestAuth

# Shelly Gen2 requires the fixed user name "admin" for digest authentication.
SHELLY_USERNAME = "admin"
REQUEST_TIMEOUT = 15
# A busy Shelly answers HTTP 429 (Too Many Requests), sometimes wrongly (firmware 2.0.0 does so
# now and then). The request is repeated a few times before the poll counts as failed.
MAX_ATTEMPTS = 3
DEFAULT_RETRY_DELAY = 2.0
MAX_RETRY_DELAY = 10.0


class ShellyApiError(Exception):
    pass


class ShellyAuthError(ShellyApiError):
    """The Shelly rejected the credentials or requires authentication."""


class ShellyNotSupportedError(ShellyApiError):
    """The requested RPC method does not exist (e.g. EMData in monophase profile)."""


class ShellyBusyError(ShellyApiError):
    """The Shelly kept answering 429 Too Many Requests."""


class _SharedDigestAuth(HTTPDigestAuth):
    """Digest authentication whose challenge (nonce) is shared by all threads.

    `requests` keeps the digest state per thread. Home Assistant runs every call on some worker
    thread, so most calls would start with an unauthenticated request just to provoke a
    challenge. Shelly firmware 2.x treats a steady stream of those as a brute-force attempt and
    answers with HTTP 429. With one shared state the stored nonce is sent up front, and a new
    challenge is only needed when the Shelly has dropped it. All calls are serialized by the
    lock in ShellyApi, so sharing the state is safe.
    """

    def __init__(self, username: str, password: str) -> None:
        super().__init__(username, password)
        self._thread_local = SimpleNamespace()


def _retry_delay(response: requests.Response, attempt: int) -> float:
    """Seconds to wait before the next attempt: the Retry-After header, else a growing delay."""
    try:
        delay = float(response.headers.get("Retry-After", ""))
    except ValueError:
        delay = DEFAULT_RETRY_DELAY * attempt
    return min(max(delay, 0.0), MAX_RETRY_DELAY)


class ShellyApi:
    """Blocking client; call its methods via hass.async_add_executor_job."""

    def __init__(self, host: str, username: str | None = None, password: str | None = None) -> None:
        self.host = host.strip().removeprefix("http://").removeprefix("https://").rstrip("/")
        self._lock = threading.Lock()
        self._session = requests.Session()
        if password:
            # Shelly Gen2 uses SHA-256 digest (RFC 7616), which requests supports.
            self._session.auth = _SharedDigestAuth(username or SHELLY_USERNAME, password)

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                # HTTPDigestAuth keeps per-thread state; the lock keeps calls sequential.
                with self._lock:
                    response = self._session.get(
                        f"http://{self.host}{path}", params=params, timeout=REQUEST_TIMEOUT
                    )
                if response.status_code != 429:
                    break
                if attempt == MAX_ATTEMPTS:
                    raise ShellyBusyError(
                        f"The Shelly is busy (HTTP 429 Too Many Requests, {MAX_ATTEMPTS} attempts)"
                    )
                time.sleep(_retry_delay(response, attempt))
            if response.status_code == 401:
                raise ShellyAuthError("Authentication failed")
            if response.status_code == 404:
                raise ShellyNotSupportedError(f"{path} is not supported by the device")
            response.raise_for_status()
            return response.json()
        except ShellyApiError:
            raise
        except (requests.RequestException, ValueError) as err:
            raise ShellyApiError(str(err)) from err

    def get_data(self, timestamp: int) -> dict:
        return self._get("/rpc/EMData.GetData", {"id": 0, "ts": timestamp})

    def get_device_info(self) -> dict:
        return self._get("/rpc/Shelly.GetDeviceInfo")

    def get_unixtime(self) -> int | None:
        """The Shelly's clock (Unix time), or None while it has no valid time."""
        return self._get("/rpc/Sys.GetStatus").get("unixtime")

    def close(self) -> None:
        self._session.close()
