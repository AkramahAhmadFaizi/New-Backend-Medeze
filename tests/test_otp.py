"""Phone OTP flow end to end, with a fake DB and the fake SMS provider."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.services.clients as clients_svc
import app.services.otp as otp_svc
from app.config import Settings
from app.integrations.otp_provider import FakeOtpProvider, OtpProviderError
from app.main import app
from tests.fakes import FakeSupabase

PHONE = "+919000000011"


@pytest.fixture
def env(monkeypatch):
    db, provider = FakeSupabase(), FakeOtpProvider()
    monkeypatch.setattr(otp_svc, "get_supabase", lambda: db)
    monkeypatch.setattr(clients_svc, "get_supabase", lambda: db)
    monkeypatch.setattr(otp_svc, "get_otp_provider", lambda: provider)
    return TestClient(app), db, provider


def send(c, phone=PHONE):
    return c.post("/auth/otp/send", json={"phone": phone})


def verify(c, code, phone=PHONE):
    return c.post("/auth/otp/verify", json={"phone": phone, "code": code})


def otp_rows(db, phone=PHONE):
    return [r for r in db.db["otp_verifications"] if r["phone"] == phone]


# ---------------- send ----------------
def test_send_records_row_without_code(env):
    c, db, p = env
    r = send(c, "+91 90000 00011")
    assert r.status_code == 202 and r.json()["expires_in"] == 600
    (row,) = otp_rows(db)
    assert row["status"] == "sent" and row["provider"] == "fake"
    assert p.last_code(PHONE) not in str(row)  # code never stored


def test_send_rejects_bad_phone_and_whatsapp(env):
    c, _, _ = env
    assert send(c, "98765").status_code == 422
    assert c.post("/auth/otp/send", json={"phone": PHONE, "channel": "whatsapp"}).status_code == 422


def test_phone_rate_limit(env):
    c, _, _ = env
    assert [send(c).status_code for _ in range(4)] == [202, 202, 202, 429]


def test_ip_rate_limit(env, monkeypatch):
    c, db, _ = env
    monkeypatch.setattr(otp_svc, "_clean_ip", lambda ip: "10.0.0.1")
    codes = [send(c, f"+9190000001{i:02d}").status_code for i in range(11)]
    assert codes[:10] == [202] * 10 and codes[10] == 429


def test_new_send_retires_old_code(env):
    c, db, p = env
    send(c); send(c)
    assert [r["status"] for r in otp_rows(db)] == ["expired", "sent"]


def test_provider_failure_is_502_and_counted(env, monkeypatch):
    c, db, p = env
    def boom(*a): raise OtpProviderError("down")
    monkeypatch.setattr(p, "send", boom)
    assert send(c).status_code == 502
    assert otp_rows(db)[0]["status"] == "failed"


# ---------------- verify ----------------
def test_verify_new_client_then_create(env):
    c, db, p = env
    send(c)
    r = verify(c, p.last_code(PHONE))
    body = r.json()
    assert r.status_code == 200 and body["verified"] and body["is_new_client"] and body["client_id"] is None
    assert otp_rows(db)[0]["status"] == "verified"

    auth = {"Authorization": f"Bearer {body['access_token']}"}
    created = c.post("/clients", json={"phone": PHONE, "source": "web"}, headers=auth)
    assert created.status_code == 201 and created.json()["phone_verified"] is True


def test_verify_existing_client_marks_verified(env):
    c, db, p = env
    db.db["clients"].append({"id": "11111111-1111-1111-1111-111111111111", "phone": PHONE,
                             "phone_verified_at": None})
    send(c)
    body = verify(c, p.last_code(PHONE)).json()
    assert body["client_id"] == "11111111-1111-1111-1111-111111111111" and not body["is_new_client"]
    assert db.db["clients"][0]["phone_verified_at"] is not None


def test_code_is_single_use(env):
    c, _, p = env
    send(c)
    code = p.last_code(PHONE)
    assert verify(c, code).status_code == 200
    assert verify(c, code).status_code == 400


def test_wrong_code_counts_and_burns_after_max(env):
    c, db, p = env
    send(c)
    good = p.last_code(PHONE)
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        assert verify(c, bad).json()["error"]["code"] == "invalid_code"
    assert otp_rows(db)[0]["status"] == "failed"
    assert verify(c, good).status_code == 400  # burned


def test_expired_code(env):
    c, db, p = env
    send(c)
    otp_rows(db)[0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert verify(c, p.last_code(PHONE)).status_code == 400
    assert otp_rows(db)[0]["status"] == "expired"


def test_verify_without_send(env):
    c, _, _ = env
    assert verify(c, "123456").status_code == 400


def test_bad_code_format(env):
    c, _, _ = env
    assert verify(c, "12ab").status_code == 422


# ---------------- token on POST /clients ----------------
def test_create_client_needs_token(env):
    c, _, _ = env
    r = c.post("/clients", json={"phone": PHONE, "source": "web"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "missing_token"
    r = c.post("/clients", json={"phone": PHONE, "source": "web"}, headers={"Authorization": "Bearer junk"})
    assert r.status_code == 401


def test_token_for_other_phone_is_403(env):
    c, _, p = env
    send(c)
    token = verify(c, p.last_code(PHONE)).json()["access_token"]
    r = c.post("/clients", json={"phone": "+919000000099", "source": "web"},
               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_tampered_token_is_401(env):
    c, _, p = env
    send(c)
    token = verify(c, p.last_code(PHONE)).json()["access_token"]
    r = c.post("/clients", json={"phone": PHONE, "source": "web"},
               headers={"Authorization": f"Bearer {token[:-2]}xx"})
    assert r.status_code == 401


# ---------------- config guards ----------------
BASE = dict(_env_file=None, supabase_url="https://x.supabase.co",
            supabase_secret_key="sb_secret_x", otp_token_secret="s" * 40)


def test_config_guards():
    with pytest.raises(ValidationError):
        Settings(**BASE, app_env="production", otp_provider="fake")
    with pytest.raises(ValidationError):
        Settings(**{**BASE, "otp_token_secret": "short"})
    with pytest.raises(ValidationError):
        Settings(**BASE, otp_provider="twilio")  # removed provider


# ---------------- country + daily budget guard ----------------
def test_non_indian_number_rejected(env):
    c, db, _ = env
    r = send(c, "+14155550100")
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_country"
    assert db.db["otp_verifications"] == []  # nothing sent, nothing paid


def test_daily_budget_cap(env, monkeypatch):
    c, _, _ = env
    capped = otp_svc.get_settings().model_copy(update={"otp_max_sends_per_day": 2})
    monkeypatch.setattr(otp_svc, "get_settings", lambda: capped)
    codes = [send(c, f"+9190000002{i:02d}").status_code for i in range(3)]
    assert codes == [202, 202, 503]


# ---------------- 2Factor adapter (HTTP mocked, nothing sent) ----------------
from app.integrations.otp_provider import TwoFactorProvider  # noqa: E402

KEY = "secret-key-123"


def twofactor(handler, template=None):
    return TwoFactorProvider(KEY, template, transport=httpx.MockTransport(handler))


def test_2factor_send_url_and_session():
    seen = {}
    def handler(req):
        seen["path"] = req.url.path
        return httpx.Response(200, json={"Status": "Success", "Details": "SESS-1"})
    assert twofactor(handler, "LOGIN_OTP").send(PHONE, "sms") == "SESS-1"
    assert seen["path"] == f"/API/V1/{KEY}/SMS/919000000011/AUTOGEN/LOGIN_OTP"  # no '+'


@pytest.mark.parametrize("details,status,expected", [
    ("OTP Matched", "Success", "approved"),
    ("OTP Mismatch", "Error", "pending"),
    ("OTP Expired", "Success", "expired"),
    ("Invalid Session", "Error", "failed"),
])
def test_2factor_check_mapping(details, status, expected):
    t = twofactor(lambda r: httpx.Response(200, json={"Status": status, "Details": details}))
    assert t.check(PHONE, "123456", "SESS-1") == expected


def test_2factor_errors_never_leak_key():
    for handler in (lambda r: httpx.Response(200, json={"Status": "Error", "Details": "Invalid API Key"}),
                    lambda r: httpx.Response(502, text="<html>bad gateway</html>")):
        with pytest.raises(OtpProviderError) as e:
            twofactor(handler).send(PHONE, "sms")
        assert KEY not in str(e.value)
    def down(req): raise httpx.ConnectError("boom", request=req)
    with pytest.raises(OtpProviderError) as e:
        twofactor(down).send(PHONE, "sms")
    assert KEY not in str(e.value)


def test_2factor_config_needs_key():
    with pytest.raises(ValidationError):
        Settings(**BASE, otp_provider="2factor")
    assert Settings(**BASE, otp_provider="2factor", twofactor_api_key="k").otp_provider == "2factor"