"""Book a session in BOTH databases.

Medisina (old DB) is the source of truth for availability, so it goes first:
  1. check client + (our own) slot state             -> new DB, read only
  2. fetch doctor profile                            -> Medisina
  3. create appointment (this holds the slot)        -> Medisina
  4. upsert therapist, slot (booked), insert session -> new DB
If step 4 fails, the Medisina appointment is cancelled so the databases never
disagree. The shared key is therapists.medisina_doctor_id (see DATABASE_SYNC.md).
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from uuid import UUID

from app.db import get_supabase
from app.errors import AppError
from app.medisina import operations as ops
from app.medisina.client import MedisinaError, get_medisina
from app.schemas.bookings import BookingCreate, BookingOut
from app.services.clients import get_client

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ public
def create_booking(data: BookingCreate) -> BookingOut:
    get_client(data.client_id)  # 404 if the client does not exist
    start = data.slot_start_utc.astimezone(timezone.utc)
    sb = get_supabase()

    # Cheap early exit if we already know this slot is taken in the new DB.
    therapist = _find_therapist(data.doctor_id)
    if therapist and _live_session_for_start(therapist["id"], start):
        raise AppError(409, "slot_taken", "This slot is already booked.")

    med = get_medisina()
    doctor = med.call(ops.GET_DOCTOR, path_params={"id": data.doctor_id})
    appt = med.call(ops.CREATE_APPOINTMENT, json={
        "doctorId": data.doctor_id,
        "slotStartUtc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "appointmentType": data.appointment_type,
        **({"reasonForVisit": data.concern} if data.concern else {}),
    })
    appointment_id = int(appt["appointmentId"])

    # Same request replayed: Medisina returned the existing appointment.
    if appt.get("replayed"):
        existing = _session_by_appointment(appointment_id)
        if existing:
            return _to_out(existing, doctor_id=data.doctor_id,
                           hold=_parse(appt.get("holdExpiresAt")))

    slot_id: Optional[str] = None
    try:
        fee = _fetch_fee(appointment_id)
        t_start, t_end = _parse(appt["scheduledStartAt"]), _parse(appt["scheduledEndAt"])
        therapist = _upsert_therapist(data.doctor_id, doctor, fee, t_start, t_end)
        slot_id = _book_slot(therapist["id"], t_start, t_end)
        row = sb.table("sessions").insert({
            "client_id": str(data.client_id),
            "therapist_id": therapist["id"],
            "slot_id": slot_id,
            "concern": data.concern,
            "start_at": t_start.isoformat(),
            "end_at": t_end.isoformat(),
            "status": "pending_payment",
            "list_price": str(fee),
            "discount_amount": "0",
            "final_amount": str(fee),
            "medisina_appointment_id": appointment_id,
            "medisina_patient_id": appt.get("patientId"),
        }).execute().data[0]
    except Exception:
        _rollback(appointment_id, slot_id)
        raise
    return _to_out(row, doctor_id=data.doctor_id, hold=_parse(appt.get("holdExpiresAt")))


def get_booking(session_id: UUID) -> BookingOut:
    res = get_supabase().table("sessions").select("*").eq("id", str(session_id)).limit(1).execute()
    if not res.data:
        raise AppError(404, "not_found", "Session not found.")
    return _to_out(res.data[0])


# ------------------------------------------------------------------ new-DB helpers
def _find_therapist(doctor_id: int) -> Optional[dict]:
    res = (get_supabase().table("therapists").select("id,medisina_doctor_id")
           .eq("medisina_doctor_id", doctor_id).limit(1).execute())
    return res.data[0] if res.data else None


def _live_session_for_start(therapist_id: str, start: datetime) -> Optional[dict]:
    sb = get_supabase()
    slot = (sb.table("therapist_slots").select("id").eq("therapist_id", therapist_id)
            .eq("start_at", start.isoformat()).limit(1).execute())
    if not slot.data:
        return None
    live = (sb.table("sessions").select("id").eq("slot_id", slot.data[0]["id"])
            .neq("status", "cancelled").limit(1).execute())
    return live.data[0] if live.data else None


def _session_by_appointment(appointment_id: int) -> Optional[dict]:
    res = (get_supabase().table("sessions").select("*")
           .eq("medisina_appointment_id", appointment_id).limit(1).execute())
    return res.data[0] if res.data else None


def _upsert_therapist(doctor_id: int, doctor: dict[str, Any], fee: Decimal,
                      start: datetime, end: datetime) -> dict:
    sb = get_supabase()
    name = " ".join(p for p in (doctor.get("salutation"), doctor.get("firstName"),
                                doctor.get("lastName")) if p) or f"Doctor {doctor_id}"
    minutes = min(max(int((end - start).total_seconds() // 60), 10), 240)
    profile = {
        "full_name": name,
        "photo_url": doctor.get("profilePictureUrl"),
        "about": doctor.get("bio"),
        "specialties": [s["specialtyName"] for s in doctor.get("specialties") or []],
        "session_minutes": minutes,
        "is_active": True,
    }
    existing = _find_therapist(doctor_id)
    if existing:
        if fee > 0:
            profile["session_fee"] = str(fee)
        return sb.table("therapists").update(profile).eq("id", existing["id"]).execute().data[0]
    return sb.table("therapists").insert(
        {**profile, "medisina_doctor_id": doctor_id, "session_fee": str(fee)}
    ).execute().data[0]


def _book_slot(therapist_id: str, start: datetime, end: datetime) -> str:
    sb = get_supabase()
    fields = {"end_at": end.isoformat(), "status": "booked", "held_until": None}
    found = (sb.table("therapist_slots").select("id").eq("therapist_id", therapist_id)
             .eq("start_at", start.isoformat()).limit(1).execute())
    if found.data:
        slot_id = found.data[0]["id"]
        if _live_session_for_start(therapist_id, start):
            raise AppError(409, "slot_taken", "This slot is already booked.")
        sb.table("therapist_slots").update(fields).eq("id", slot_id).execute()
        return slot_id
    return sb.table("therapist_slots").insert(
        {"therapist_id": therapist_id, "start_at": start.isoformat(), **fields}
    ).execute().data[0]["id"]


def _rollback(appointment_id: int, slot_id: Optional[str]) -> None:
    """Undo what we did. Never raises: the original error is what the caller needs."""
    try:
        get_medisina().call(ops.CANCEL_APPOINTMENT, path_params={"id": appointment_id})
    except Exception:
        log.exception("ROLLBACK FAILED: Medisina appointment %s is still held and has no "
                      "matching session in the new DB. Cancel it manually.", appointment_id)
    if slot_id:
        try:
            get_supabase().table("therapist_slots").update(
                {"status": "open"}).eq("id", slot_id).execute()
        except Exception:
            log.exception("ROLLBACK FAILED: could not reopen slot %s", slot_id)


# ------------------------------------------------------------------ misc
def _fetch_fee(appointment_id: int) -> Decimal:
    """Price comes from Medisina's appointment; 0 if it has none (or the lookup fails)."""
    try:
        data = get_medisina().call(ops.GET_APPOINTMENT, path_params={"id": appointment_id})
        return Decimal(str(data.get("fee") or 0))
    except (MedisinaError, InvalidOperation):
        log.warning("Could not read fee for appointment %s; using 0", appointment_id)
        return Decimal("0")


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_out(row: dict, doctor_id: Optional[int] = None, hold: Optional[datetime] = None) -> BookingOut:
    if doctor_id is None:
        t = (get_supabase().table("therapists").select("medisina_doctor_id")
             .eq("id", row["therapist_id"]).limit(1).execute())
        doctor_id = t.data[0]["medisina_doctor_id"] if t.data else None
    return BookingOut(
        session_id=row["id"], client_id=row["client_id"], therapist_id=row["therapist_id"],
        slot_id=row["slot_id"], medisina_doctor_id=doctor_id,
        medisina_appointment_id=row.get("medisina_appointment_id"),
        medisina_patient_id=row.get("medisina_patient_id"),
        start_at=row["start_at"], end_at=row["end_at"], status=row["status"],
        concern=row.get("concern"), list_price=row["list_price"],
        discount_amount=row["discount_amount"], final_amount=row["final_amount"],
        hold_expires_at=hold,
    )
