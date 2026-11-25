"""HTTP layer for bookings. No DB or Medisina code here."""
from uuid import UUID

from fastapi import APIRouter, status

from app.schemas.bookings import BookingCreate, BookingOut
from app.services import bookings as service

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking(body: BookingCreate):
    return service.create_booking(body)


@router.get("/{session_id}", response_model=BookingOut)
def get_booking(session_id: UUID):
    return service.get_booking(session_id)
