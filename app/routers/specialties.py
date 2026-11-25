"""HTTP layer for specialties (data from Medisina). No Medisina calls here."""
from fastapi import APIRouter

from app.schemas.specialties import SpecialtyList
from app.services import specialties as service

router = APIRouter(prefix="/specialties", tags=["specialties"])


@router.get("", response_model=SpecialtyList)
def list_specialties():
    return service.list_specialties()
