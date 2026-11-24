"""Required fields on clients: first_name, email, dob (create); not clearable (update)."""
import pytest
from fastapi.testclient import TestClient

import app.services.clients as clients_svc
from app.main import app
from app.tokens import issue_phone_token
from tests.fakes import FakeSupabase

PHONE = "+919000000021"
VALID = {"phone": PHONE, "source": "web", "first_name": "Asha", "email": "asha@example.com", "dob": "1995-06-15"}


@pytest.fixture
def env(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(clients_svc, "get_supabase", lambda: db)
    token, _ = issue_phone_token(PHONE, None)
    return TestClient(app), db, {"Authorization": f"Bearer {token}"}


def fields_in_error(r):
    return {d["field"] for d in r.json()["error"]["details"]}


def test_valid_create(env):
    c, _, auth = env
    r = c.post("/clients", json=VALID, headers=auth)
    assert r.status_code == 201
    body = r.json()
    assert body["first_name"] == "Asha" and body["email"] == "asha@example.com" and body["dob"] == "1995-06-15"
    assert body["last_name"] is None  # still optional


@pytest.mark.parametrize("field", ["first_name", "email", "dob"])
def test_missing_required_field(env, field):
    c, db, auth = env
    body = {k: v for k, v in VALID.items() if k != field}
    r = c.post("/clients", json=body, headers=auth)
    assert r.status_code == 422 and field in fields_in_error(r)
    assert db.db["clients"] == []


@pytest.mark.parametrize("field,value", [("first_name", None), ("first_name", "   "),
                                         ("email", None), ("email", ""), ("dob", None)])
def test_null_or_blank_required_field(env, field, value):
    c, _, auth = env
    r = c.post("/clients", json={**VALID, field: value}, headers=auth)
    assert r.status_code == 422 and field in fields_in_error(r)


def test_all_missing_reports_every_field(env):
    c, _, auth = env
    r = c.post("/clients", json={"phone": PHONE, "source": "web"}, headers=auth)
    assert {"first_name", "email", "dob"} <= fields_in_error(r)


@pytest.mark.parametrize("field", ["first_name", "email", "dob"])
def test_patch_cannot_clear_required(env, field):
    c, _, auth = env
    cid = c.post("/clients", json=VALID, headers=auth).json()["id"]
    r = c.patch(f"/clients/{cid}", json={field: None})
    assert r.status_code == 422 and field in fields_in_error(r)


def test_patch_can_change_required_and_clear_optional(env):
    c, _, auth = env
    cid = c.post("/clients", json={**VALID, "last_name": "Rao"}, headers=auth).json()["id"]
    r = c.patch(f"/clients/{cid}", json={"first_name": "Asha K", "email": "NEW@Example.com", "last_name": None})
    assert r.status_code == 200
    body = r.json()
    assert body["first_name"] == "Asha K" and body["email"] == "new@example.com" and body["last_name"] is None