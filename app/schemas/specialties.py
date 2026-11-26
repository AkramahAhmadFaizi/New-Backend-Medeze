"""Output shapes for specialties (data comes from Medisina)."""
from typing import Optional

from pydantic import BaseModel


class SpecialtyOut(BaseModel):
    specialty_id: int
    name: str
    icon_url: Optional[str] = None
    display_order: Optional[int] = None


class SpecialtyList(BaseModel):
    specialties: list[SpecialtyOut]
