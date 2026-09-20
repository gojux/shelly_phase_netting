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
