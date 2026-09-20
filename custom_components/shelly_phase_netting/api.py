from __future__ import annotations

import threading

import requests
from requests.auth import HTTPDigestAuth

# Shelly Gen2 requires the fixed user name "admin" for digest authentication.
SHELLY_USERNAME = "admin"
REQUEST_TIMEOUT = 15


class ShellyApiError(Exception):
    pass


class ShellyAuthError(ShellyApiError):
    """The Shelly rejected the credentials or requires authentication."""


class ShellyNotSupportedError(ShellyApiError):
    """The requested RPC method does not exist (e.g. EMData in monophase profile)."""


class ShellyApi:
    """Blocking client; call its methods via hass.async_add_executor_job."""

    def __init__(self, host: str, username: str | None = None, password: str | None = None) -> None:
        self.host = host.strip().removeprefix("http://").removeprefix("https://").rstrip("/")
        self._lock = threading.Lock()
        self._session = requests.Session()
        if password:
            # Shelly Gen2 uses SHA-256 digest (RFC 7616), which requests supports.
            self._session.auth = HTTPDigestAuth(username or SHELLY_USERNAME, password)

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            # HTTPDigestAuth keeps per-thread state; the lock keeps calls sequential.
            with self._lock:
                response = self._session.get(
                    f"http://{self.host}{path}", params=params, timeout=REQUEST_TIMEOUT
                )
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

    def close(self) -> None:
        self._session.close()
