"""Request/response shapes for booking a session (Medisina + Supabase)."""
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

from app.validate import InputModel, OptionalLongText, SessionStatus, Timestamp

AppointmentType = Literal["VIDEO", "AUDIO", "CHAT", "IN_PERSON", "HOME_VISIT"]


class BookingCreate(InputModel):
    client_id: UUID                       # our clients.id
    doctor_id: int                        # Medisina doctorId (= therapists.medisina_doctor_id)
    slot_start_utc: Timestamp             # exactly a start_utc returned by GET /doctors/{id}/slots
    concern: OptionalLongText = None      # sessions.concern / Medisina reasonForVisit
    appointment_type: AppointmentType = "VIDEO"


class BookingOut(BaseModel):
    session_id: UUID                      # new DB
    client_id: UUID
    therapist_id: UUID
    slot_id: UUID
    medisina_doctor_id: Optional[int]     # old DB
    medisina_appointment_id: Optional[int]
    medisina_patient_id: Optional[int]
    start_at: datetime
    end_at: datetime
    status: SessionStatus
    concern: Optional[str]
    list_price: Decimal
    discount_amount: Decimal
    final_amount: Decimal
    # Only known on the call that created the booking (Medisina holds the slot until then).
    hold_expires_at: Optional[datetime] = None
