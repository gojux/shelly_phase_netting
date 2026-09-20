import pytest
from custom_components.shelly_phase_netting.api import ShellyApi, ShellyAuthError, ShellyNotSupportedError, ShellyApiError

def test_digest_sha256_ok(fake_shelly):
    api = ShellyApi(fake_shelly.host, "admin", "secret")
    assert api.get_device_info()["mac"] == "AABBCCDDEEFF"
    api.get_data(0); api.get_data(0)
    api.close()
    # session keeps auth: first call = challenge + authed retry; later calls should not need extra 401s
    unauth = [r for r in fake_shelly.requests if not r[1]]
    print(fake_shelly.requests)
    assert len(unauth) == 1

def test_wrong_password(fake_shelly):
    api = ShellyApi(fake_shelly.host, "admin", "wrong")
    with pytest.raises(ShellyAuthError): api.get_device_info()

def test_no_password_on_protected_device(fake_shelly):
    with pytest.raises(ShellyAuthError): ShellyApi(fake_shelly.host).get_device_info()

def test_404_not_supported(fake_shelly):
    fake_shelly.emdata = False
    with pytest.raises(ShellyNotSupportedError): ShellyApi(fake_shelly.host, "admin", "secret").get_data(0)

def test_connection_refused(socket_enabled):
    with pytest.raises(ShellyApiError): ShellyApi("127.0.0.1:1").get_device_info()

def test_no_auth_device(fake_shelly):
    fake_shelly.password = None
    assert ShellyApi(fake_shelly.host).get_device_info()["mac"]


def test_a_busy_shelly_is_asked_again(fake_shelly):
    from custom_components.shelly_phase_netting.api import MAX_ATTEMPTS

    fake_shelly.busy = MAX_ATTEMPTS - 1   # 429, 429, then the answer
    api = ShellyApi(fake_shelly.host, "admin", "secret")
    assert api.get_device_info()["mac"] == "AABBCCDDEEFF"
    assert fake_shelly.busy == 0
    api.close()


def test_a_shelly_that_stays_busy_raises_a_dedicated_error(fake_shelly):
    from custom_components.shelly_phase_netting.api import MAX_ATTEMPTS, ShellyBusyError

    fake_shelly.busy = MAX_ATTEMPTS
    with pytest.raises(ShellyBusyError):
        ShellyApi(fake_shelly.host, "admin", "secret").get_device_info()


@pytest.mark.parametrize(
    ("header", "attempt", "expected"),
    [("3", 1, 3.0), (None, 1, 2.0), (None, 2, 4.0), ("999", 1, 10.0), ("Wed, 21 Oct 2026 07:28:00 GMT", 2, 4.0)],
)
def test_retry_delay_follows_retry_after_with_a_cap(header, attempt, expected):
    import requests

    from custom_components.shelly_phase_netting.api import _retry_delay

    response = requests.Response()
    if header is not None:
        response.headers["Retry-After"] = header
    assert _retry_delay(response, attempt) == expected


def _call_on_a_new_thread(function, *args):
    """Home Assistant runs every call on some worker thread; a fresh thread mimics that."""
    import threading

    result = {}

    def target():
        result["value"] = function(*args)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    return result["value"]


def test_the_digest_challenge_is_reused_across_threads(fake_shelly):
    """Firmware 2.x counts unauthenticated requests as brute-force attempts (HTTP 429)."""
    api = ShellyApi(fake_shelly.host, "admin", "secret")
    for _ in range(4):
        assert _call_on_a_new_thread(api.get_device_info)["mac"] == "AABBCCDDEEFF"
    unauthenticated = [entry for entry in fake_shelly.requests if not entry[1]]
    assert len(unauthenticated) == 1   # only the very first request needs a challenge
    api.close()


def test_an_expired_nonce_costs_one_new_challenge_and_is_then_reused(fake_shelly):
    api = ShellyApi(fake_shelly.host, "admin", "secret")
    assert _call_on_a_new_thread(api.get_device_info)["mac"] == "AABBCCDDEEFF"
    fake_shelly.nonce = "0123456789abcdef"   # the Shelly has dropped the nonce it handed out
    fake_shelly.requests.clear()
    for _ in range(3):
        assert _call_on_a_new_thread(api.get_device_info)["mac"] == "AABBCCDDEEFF"
    # first call: stale nonce rejected, fresh challenge answered; the other two go straight through
    assert [authed for _, authed in fake_shelly.requests] == [False, True, True, True]
    api.close()
