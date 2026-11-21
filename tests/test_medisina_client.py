"""MedisinaClient token flow, tested against a fake Medisina (no network)."""
import httpx
import pytest

from app.medisina import client as client_module
from app.medisina.client import (
    MedisinaAuthError,
    MedisinaClient,
    MedisinaError,
    MedisinaNetworkError,
)
from app.medisina.operations import Op

PING = Op("GET", "/ping")
DOCTOR = Op("GET", "/doctors/{id}")


class FakeMedisina:
    """Records every request and answers like Medisina does."""

    def __init__(self, expires_in=900):
        self.calls: list[httpx.Request] = []
        self.expires_in = expires_in
        self.logins = 0
        self.refreshes = 0
        self.valid_tokens: set[str] = set()
        self.refresh_ok = True
        self.login_ok = True

    def paths(self):
        return [r.url.path for r in self.calls]

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if req.url.path == "/auth/login":
            if not self.login_ok:
                return httpx.Response(401, json={"success": False, "error": {
                    "code": "INVALID_CREDENTIALS", "message": "bad password"}})
            self.logins += 1
            token = f"access-{self.logins}"
            self.valid_tokens.add(token)
            return httpx.Response(200, json={"success": True, "data": {
                "token": token, "refreshToken": f"refresh-{self.logins}",
                "expiresIn": self.expires_in}})
        if req.url.path == "/auth/refresh":
            if not self.refresh_ok:
                return httpx.Response(401, json={"success": False, "error": {
                    "code": "INVALID_REFRESH_TOKEN"}})
            self.refreshes += 1
            token = f"refreshed-{self.refreshes}"
            self.valid_tokens.add(token)
            return httpx.Response(200, json={"success": True, "data": {
                "token": token, "expiresIn": self.expires_in}})
        # any other endpoint needs a valid Bearer token
        auth = req.headers.get("Authorization", "")
        if auth.removeprefix("Bearer ") not in self.valid_tokens:
            return httpx.Response(401, json={"success": False, "error": {"code": "UNAUTHORIZED"}})
        if req.url.path == "/doctors/404":
            return httpx.Response(404, json={"success": False, "error": {
                "code": "NOT_FOUND", "message": "Doctor not found"}})
        return httpx.Response(200, json={"success": True, "data": {
            "path": req.url.path, "query": dict(req.url.params)}})


def make(fake: FakeMedisina) -> MedisinaClient:
    return MedisinaClient("https://medisina.test", "a@b.c", "pw", "PATIENT",
                          transport=httpx.MockTransport(fake))


def test_logs_in_once_then_reuses_token():
    fake = FakeMedisina()
    c = make(fake)
    assert c.call(PING) == {"path": "/ping", "query": {}}
    c.call(PING)
    assert fake.paths() == ["/auth/login", "/ping", "/ping"]
    assert fake.calls[1].headers["Authorization"] == "Bearer access-1"
    assert fake.calls[0].read() == b'{"email":"a@b.c","password":"pw","userType":"PATIENT"}'


def test_base_url_path_params_and_none_query_values():
    fake = FakeMedisina()
    data = make(fake).call(DOCTOR, path_params={"id": 7}, params={"q": "x", "city": None})
    assert data == {"path": "/doctors/7", "query": {"q": "x"}}
    assert str(fake.calls[-1].url).startswith("https://medisina.test/doctors/7")


def test_refreshes_when_token_is_about_to_expire():
    fake = FakeMedisina(expires_in=10)  # less than the 30s skew => always "expired"
    c = make(fake)
    c.call(PING)
    c.call(PING)
    assert fake.paths() == ["/auth/login", "/ping", "/auth/refresh", "/ping"]
    assert fake.calls[0].read() and b"refresh-1" in fake.calls[2].read()
    assert fake.calls[3].headers["Authorization"] == "Bearer refreshed-1"


def test_401_triggers_one_renew_and_retry():
    fake = FakeMedisina()
    c = make(fake)
    c.call(PING)
    fake.valid_tokens.clear()  # Medisina revokes the token
    assert c.call(PING)["path"] == "/ping"
    assert fake.paths() == ["/auth/login", "/ping", "/ping", "/auth/refresh", "/ping"]


def test_falls_back_to_login_when_refresh_token_is_rejected():
    fake = FakeMedisina(expires_in=10)
    c = make(fake)
    c.call(PING)
    fake.refresh_ok = False
    c.call(PING)
    assert fake.paths() == ["/auth/login", "/ping", "/auth/refresh", "/auth/login", "/ping"]
    assert fake.calls[-1].headers["Authorization"] == "Bearer access-2"


def test_bad_credentials_raise_auth_error():
    fake = FakeMedisina()
    fake.login_ok = False
    with pytest.raises(MedisinaAuthError) as e:
        make(fake).call(PING)
    assert e.value.code == "INVALID_CREDENTIALS"


def test_error_envelope_becomes_medisina_error():
    with pytest.raises(MedisinaError) as e:
        make(FakeMedisina()).call(DOCTOR, path_params={"id": 404})
    assert (e.value.upstream_status, e.value.code, e.value.message) == (404, "NOT_FOUND", "Doctor not found")


def test_success_false_with_http_200_is_an_error():
    def handler(req):
        return httpx.Response(200, json={"success": False, "error": {"code": "VALIDATION"}})
    c = MedisinaClient("https://m.test", "a", "b", "PATIENT", transport=httpx.MockTransport(handler))
    with pytest.raises(MedisinaError) as e:
        c.call(Op("GET", "/x", auth=False))
    assert (e.value.upstream_status, e.value.code) == (502, "VALIDATION")


def test_network_errors_become_502_and_504():
    def down(req):
        raise httpx.ConnectError("connection refused", request=req)

    def slow(req):
        raise httpx.ReadTimeout("too slow", request=req)

    open_op = Op("GET", "/x", auth=False)
    for handler, status in [(down, 502), (slow, 504)]:
        c = MedisinaClient("https://m.test", "a", "b", "PATIENT", transport=httpx.MockTransport(handler))
        with pytest.raises(MedisinaError) as e:
            c.call(open_op)
        assert e.value.upstream_status == status


def test_missing_expires_in_uses_default(monkeypatch):
    def handler(req):
        if req.url.path == "/auth/login":
            return httpx.Response(200, json={"success": True, "data": {"token": "t", "refreshToken": "r"}})
        return httpx.Response(200, json={"success": True, "data": 1})
    c = MedisinaClient("https://m.test", "a", "b", "PATIENT", transport=httpx.MockTransport(handler))
    c.call(PING)
    assert c._expires_at > 0 and client_module.DEFAULT_EXPIRES_IN == 300


def test_unreachable_during_login_is_network_error_not_auth_error():
    def down(req):
        raise httpx.ConnectError("connection refused", request=req)
    c = MedisinaClient("https://m.test", "a", "b", "PATIENT", transport=httpx.MockTransport(down))
    with pytest.raises(MedisinaNetworkError) as e:
        c.call(PING)
    assert not isinstance(e.value, MedisinaAuthError)
    assert e.value.upstream_status == 502
