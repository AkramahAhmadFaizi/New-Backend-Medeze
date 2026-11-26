"""Booking flow against a fake Medisina and a fake Supabase (no network, no .env)."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import register_error_handlers
from app.medisina import operations as ops
from app.medisina.client import MedisinaError
from app.routers import bookings as bookings_router
from app.routers import specialties as specialties_router
from app.services import bookings as service

CLIENT_ID = str(uuid4())
START = "2026-11-25T04:30:00Z"

DOCTOR = {"doctorId": 7, "firstName": "Asha", "lastName": "Rao", "salutation": "Dr.",
          "profilePictureUrl": None, "bio": "Hi",
          "specialties": [{"specialtyId": 2, "specialtyName": "Psychology", "isPrimary": True}]}
APPT = {"appointmentId": 99, "patientId": 5, "doctorId": 7,
        "scheduledStartAt": START, "scheduledEndAt": "2026-11-25T05:20:00.000Z",
        "holdExpiresAt": "2026-11-25T03:00:00Z", "replayed": False}


class FakeMedisina:
    def __init__(self, over=None):
        self.responses = {
            ops.GET_DOCTOR: DOCTOR, ops.CREATE_APPOINTMENT: APPT,
            ops.GET_APPOINTMENT: {"fee": 1500}, ops.CANCEL_APPOINTMENT: {},
            ops.LIST_SPECIALTIES: {"specialties": [
                {"specialtyId": 2, "specialtyName": "Psychology", "iconUrl": None, "displayOrder": 2},
                {"specialtyId": 1, "specialtyName": "Counselling", "iconUrl": None, "displayOrder": 1}]},
        }
        self.responses.update(over or {})
        self.calls = []

    def call(self, op, *, path_params=None, params=None, json=None):
        self.calls.append((op, json))
        r = self.responses[op]
        if isinstance(r, Exception):
            raise r
        return r

    def ops_called(self):
        return [c[0] for c in self.calls]


class Result:
    def __init__(self, data):
        self.data = data


class FakeTable:
    """Just enough of supabase-py's query builder, backed by lists of dicts."""
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.op, self.payload = db, name, [], "select", None

    def select(self, *_):
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def update(self, row):
        self.op, self.payload = "update", row
        return self

    def eq(self, k, v):
        self.filters.append((k, v, True))
        return self

    def neq(self, k, v):
        self.filters.append((k, v, False))
        return self

    def limit(self, _):
        return self

    def _rows(self):
        return [r for r in self.db[self.name]
                if all((str(r.get(k)) == str(v)) == eq for k, v, eq in self.filters)]

    def execute(self):
        if self.name in self.db.get("_fail", set()) and self.op != "select":
            raise RuntimeError("boom")
        if self.op == "insert":
            row = {"id": str(uuid4()), **self.payload}
            self.db[self.name].append(row)
            return Result([row])
        rows = self._rows()
        if self.op == "update":
            for r in rows:
                r.update(self.payload)
        return Result([dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, fail=()):
        self.db = {"clients": [{"id": CLIENT_ID}], "therapists": [], "therapist_slots": [],
                   "sessions": [], "_fail": set(fail)}

    def table(self, name):
        return FakeTable(self.db, name)


@pytest.fixture
def env(monkeypatch):
    def make(med=None, sb=None):
        med, sb = med or FakeMedisina(), sb or FakeSupabase()
        monkeypatch.setattr(service, "get_medisina", lambda: med)
        monkeypatch.setattr(service, "get_supabase", lambda: sb)
        monkeypatch.setattr(service, "get_client", lambda _id: None)
        return med, sb
    return make


def body(**over):
    return {"client_id": CLIENT_ID, "doctor_id": 7, "slot_start_utc": START, **over}


def test_booking_writes_both_databases(env):
    med, sb = env()
    out = service.create_booking(service.BookingCreate(**body(concern="anxiety")))
    assert ops.CREATE_APPOINTMENT in med.ops_called()
    assert med.calls[1][1]["slotStartUtc"] == START and med.calls[1][1]["reasonForVisit"] == "anxiety"
    th = sb.db["therapists"][0]
    assert th["medisina_doctor_id"] == 7 and th["full_name"] == "Dr. Asha Rao"
    assert th["session_minutes"] == 50 and th["session_fee"] == "1500"
    assert sb.db["therapist_slots"][0]["status"] == "booked"
    s = sb.db["sessions"][0]
    assert s["medisina_appointment_id"] == 99 and s["status"] == "pending_payment"
    assert s["final_amount"] == "1500"
    assert out.medisina_appointment_id == 99 and out.medisina_doctor_id == 7


def test_new_db_failure_cancels_medisina_appointment(env):
    med, sb = env(sb=FakeSupabase(fail={"sessions"}))
    with pytest.raises(RuntimeError):
        service.create_booking(service.BookingCreate(**body()))
    assert ops.CANCEL_APPOINTMENT in med.ops_called()
    assert sb.db["therapist_slots"][0]["status"] == "open"
    assert sb.db["sessions"] == []


def test_medisina_failure_writes_nothing(env):
    med, sb = env(med=FakeMedisina({ops.CREATE_APPOINTMENT: MedisinaError(409, "SLOT_UNAVAILABLE", "x")}))
    with pytest.raises(MedisinaError):
        service.create_booking(service.BookingCreate(**body()))
    assert sb.db["therapists"] == [] and sb.db["sessions"] == []


def test_slot_already_booked_in_new_db_is_409_without_calling_medisina(env):
    med, sb = env()
    service.create_booking(service.BookingCreate(**body()))
    med.calls.clear()
    with pytest.raises(service.AppError) as e:
        service.create_booking(service.BookingCreate(**body()))
    assert e.value.status == 409 and ops.CREATE_APPOINTMENT not in med.ops_called()


def test_replayed_request_returns_existing_session(env):
    med, sb = env()
    first = service.create_booking(service.BookingCreate(**body()))
    sb.db["sessions"][0]["status"] = "cancelled"  # bypass the early slot check
    med.responses[ops.CREATE_APPOINTMENT] = {**APPT, "replayed": True}
    again = service.create_booking(service.BookingCreate(**body()))
    assert again.session_id == first.session_id and len(sb.db["sessions"]) == 1


def test_endpoints(env, monkeypatch):
    env()
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(bookings_router.router)
    app.include_router(specialties_router.router)
    from app.services import specialties as spec_service
    monkeypatch.setattr(spec_service, "get_medisina", lambda: FakeMedisina())
    c = TestClient(app)
    r = c.post("/bookings", json=body())
    assert r.status_code == 201, r.text
    assert c.get(f"/bookings/{r.json()['session_id']}").status_code == 200
    assert c.post("/bookings", json=body(slot_start_utc="2026-11-25T04:30:00")).status_code == 422
    assert c.post("/bookings", json=body(extra=1)).status_code == 422
    names = [s["name"] for s in c.get("/specialties").json()["specialties"]]
    assert names == ["Counselling", "Psychology"]
