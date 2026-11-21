"""Doctors service + router, against a fake Medisina client (no network, no .env)."""
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import register_error_handlers
from app.medisina import operations as ops
from app.medisina.client import MedisinaError
from app.routers import doctors as doctors_router
from app.services import doctors as service

BROWSE_DOCTOR = {  # DoctorSearchResult shape (no q)
    "doctorId": 7, "firstName": "Asha", "lastName": "Rao", "salutation": "Dr.",
    "profilePictureUrl": None, "yearsOfExperience": 12, "ratingAvgOverall": 4.6,
    "totalReviews": 31, "isAcceptingPatients": True,
    "primaryLocation": {"city": "Pune", "state": "MH"},
    "specialties": [
        {"specialtyId": 1, "specialtyName": "Psychiatry", "isPrimary": False},
        {"specialtyId": 2, "specialtyName": "Psychology", "isPrimary": True},
    ],
}
LITE_DOCTOR = {  # DoctorSearchLite shape (q set)
    "doctorId": 8, "firstName": "Ravi", "lastName": "Iyer", "salutation": None,
    "specialty": "Counselling", "city": "Delhi", "profilePictureUrl": "https://x/y.png",
}


class FakeMedisina:
    def __init__(self, responses):
        self.responses = responses  # {op: data or Exception}
        self.calls = []

    def call(self, op, *, path_params=None, params=None, json=None):
        self.calls.append((op, path_params, params))
        result = self.responses[op]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def fake(monkeypatch):
    f = FakeMedisina({
        ops.SEARCH_DOCTORS: {"doctors": [BROWSE_DOCTOR, LITE_DOCTOR], "total": 2,
                             "limit": 20, "offset": 0},
        ops.GET_AVAILABLE_SLOTS: {
            "date": "2026-11-25", "doctorTimezone": "Asia/Kolkata",
            "slots": [{"startUtc": "2026-11-25T04:30:00Z", "endUtc": "2026-11-25T05:20:00.000Z"}],
        },
    })
    monkeypatch.setattr(service, "get_medisina", lambda: f)
    return f


@pytest.fixture
def api():
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(doctors_router.router)
    return TestClient(app)


def test_list_flattens_both_doctor_shapes(fake):
    result = service.list_doctors(city="Pune")
    a, b = result.doctors
    assert (a.doctor_id, a.display_name, a.specialty, a.city, a.rating) == \
        (7, "Dr. Asha Rao", "Psychology", "Pune", 4.6)
    assert (b.doctor_id, b.display_name, b.specialty, b.city, b.rating) == \
        (8, "Ravi Iyer", "Counselling", "Delhi", None)
    _, _, params = fake.calls[0]
    assert params["city"] == "Pune" and params["specialtyId"] is None


def test_slots_converted_to_doctor_timezone(fake):
    result = service.get_doctor_slots(7, date(2026, 11, 25))
    slot = result.slots[0]
    assert slot.start_utc.isoformat() == "2026-11-25T04:30:00+00:00"
    assert slot.start_local.isoformat() == "2026-11-25T10:00:00+05:30"
    assert slot.end_local.isoformat() == "2026-11-25T10:50:00+05:30"
    _, path_params, params = fake.calls[0]
    assert path_params == {"id": 7} and params == {"date": "2026-11-25"}


def test_unknown_timezone_leaves_local_times_empty(fake):
    fake.responses[ops.GET_AVAILABLE_SLOTS]["doctorTimezone"] = "Mars/Olympus"
    slot = service.get_doctor_slots(7).slots[0]
    assert slot.start_local is None and slot.start_utc is not None


def test_routes_return_snake_case_json(fake, api):
    r = api.get("/doctors", params={"limit": 5})
    assert r.status_code == 200
    assert r.json()["doctors"][0]["display_name"] == "Dr. Asha Rao"
    r = api.get("/doctors/7/slots", params={"date": "2026-11-25"})
    assert r.status_code == 200
    assert r.json()["doctor_timezone"] == "Asia/Kolkata"


def test_bad_input_rejected_before_calling_medisina(fake, api):
    assert api.get("/doctors", params={"limit": 500}).status_code == 422
    assert api.get("/doctors/7/slots", params={"date": "25-11-2026"}).status_code == 422
    assert fake.calls == []


@pytest.mark.parametrize("upstream, status, code", [
    (MedisinaError(404, "DOCTOR_NOT_FOUND", "nope"), 404, "medisina_doctor_not_found"),
    (MedisinaError(401, "UNAUTHORIZED", "bad token"), 502, "medisina_auth_failed"),
    (MedisinaError(504, "TIMEOUT", "slow"), 504, "medisina_timeout"),
    (MedisinaError(500, "INTERNAL_SERVER_ERROR", "boom"), 502, "medisina_error"),
])
def test_medisina_errors_mapped(fake, api, upstream, status, code):
    fake.responses[ops.GET_AVAILABLE_SLOTS] = upstream
    r = api.get("/doctors/99/slots")
    assert r.status_code == status
    assert r.json()["error"]["code"] == code
