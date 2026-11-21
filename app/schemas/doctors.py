"""Output shapes for doctors and their time slots (data comes from Medisina).

Medisina sends camelCase and two different doctor shapes:
  - browse mode (no `q`):  DoctorSearchResult  (specialties[], primaryLocation{city})
  - search mode (`q` set): DoctorSearchLite    (specialty, city)
services/doctors.py flattens both into DoctorSummary, so callers see ONE shape.
"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class DoctorSummary(BaseModel):
    doctor_id: int
    display_name: str                   # "Dr. Asha Rao"
    first_name: str
    last_name: str
    salutation: Optional[str]
    profile_picture_url: Optional[str]
    specialty: Optional[str]            # primary specialty name
    city: Optional[str]
    # Only present in browse mode (no `q`); None in search mode.
    years_of_experience: Optional[float] = None
    rating: Optional[float] = None
    total_reviews: Optional[int] = None
    is_accepting_patients: Optional[bool] = None


class DoctorList(BaseModel):
    doctors: list[DoctorSummary]
    total: int
    limit: Optional[int]
    offset: Optional[int]


class TimeSlot(BaseModel):
    start_utc: datetime
    end_utc: datetime
    # Same instant in the doctor's timezone (None if the timezone is unknown).
    start_local: Optional[datetime]
    end_local: Optional[datetime]


class DoctorSlots(BaseModel):
    doctor_id: int
    date: date                          # the doctor's calendar day
    doctor_timezone: str
    slots: list[TimeSlot]
