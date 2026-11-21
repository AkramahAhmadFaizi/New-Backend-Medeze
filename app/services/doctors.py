"""Business logic for doctors. Routers call these; these call Medisina."""
from datetime import date, datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.medisina import operations as ops
from app.medisina.client import get_medisina
from app.schemas.doctors import DoctorList, DoctorSlots, DoctorSummary, TimeSlot


def list_doctors(
    q: Optional[str] = None,
    specialty_id: Optional[int] = None,
    city: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> DoctorList:
    data = get_medisina().call(
        ops.SEARCH_DOCTORS,
        params={"q": q, "specialtyId": specialty_id, "city": city,
                "language": language, "limit": limit, "offset": offset},
    )
    return DoctorList(
        doctors=[_to_summary(d) for d in data.get("doctors") or []],
        total=int(data.get("total") or 0),
        limit=data.get("limit", limit),
        offset=data.get("offset", offset),
    )


def get_doctor_slots(doctor_id: int, day: Optional[date] = None) -> DoctorSlots:
    """Free slots for one doctor on one day (Medisina picks the day if none given)."""
    data = get_medisina().call(
        ops.GET_AVAILABLE_SLOTS,
        path_params={"id": doctor_id},
        params={"date": day.isoformat() if day else None},
    )
    tz_name = data.get("doctorTimezone") or "UTC"
    tz = _zone(tz_name)
    slots = []
    for s in data.get("slots") or []:
        start, end = _parse_utc(s["startUtc"]), _parse_utc(s["endUtc"])
        slots.append(TimeSlot(
            start_utc=start,
            end_utc=end,
            start_local=start.astimezone(tz) if tz else None,
            end_local=end.astimezone(tz) if tz else None,
        ))
    return DoctorSlots(doctor_id=doctor_id, date=data["date"],
                       doctor_timezone=tz_name, slots=slots)


# ---------------------------------------------------------------- helpers
def _to_summary(d: dict[str, Any]) -> DoctorSummary:
    """Flatten either Medisina doctor shape (browse or search mode) into one."""
    specialty = d.get("specialty")                       # search-mode shape
    if specialty is None and d.get("specialties"):       # browse-mode shape
        specs = d["specialties"]
        primary = next((s for s in specs if s.get("isPrimary")), specs[0])
        specialty = primary.get("specialtyName")

    city = d.get("city")
    if city is None and isinstance(d.get("primaryLocation"), dict):
        city = d["primaryLocation"].get("city")

    name = " ".join(p for p in (d.get("salutation"), d["firstName"], d["lastName"]) if p)
    return DoctorSummary(
        doctor_id=d["doctorId"],
        display_name=name,
        first_name=d["firstName"],
        last_name=d["lastName"],
        salutation=d.get("salutation"),
        profile_picture_url=d.get("profilePictureUrl"),
        specialty=specialty,
        city=city,
        years_of_experience=d.get("yearsOfExperience"),
        rating=d.get("ratingAvgOverall"),
        total_reviews=d.get("totalReviews"),
        is_accepting_patients=d.get("isAcceptingPatients"),
    )


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _zone(name: str) -> Optional[ZoneInfo]:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
