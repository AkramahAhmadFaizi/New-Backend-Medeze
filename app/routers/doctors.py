"""HTTP layer for doctors (data from Medisina). No Medisina calls here."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query

from app.schemas.doctors import DoctorList, DoctorSlots
from app.services import doctors as service

router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.get("", response_model=DoctorList)
def list_doctors(
    q: Optional[str] = Query(None, min_length=1, max_length=100, description="Name search"),
    specialty_id: Optional[int] = Query(None, ge=1),
    city: Optional[str] = Query(None, min_length=1, max_length=100),
    language: Optional[str] = Query(None, min_length=2, max_length=10, examples=["en"]),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return service.list_doctors(q, specialty_id, city, language, limit, offset)


@router.get("/{doctor_id}/slots", response_model=DoctorSlots)
def get_doctor_slots(
    doctor_id: int,
    date: Optional[date] = Query(None, description="YYYY-MM-DD, the doctor's calendar day"),
):
    return service.get_doctor_slots(doctor_id, date)
