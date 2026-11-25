"""Business logic for specialties. Data comes from Medisina."""
from app.medisina import operations as ops
from app.medisina.client import get_medisina
from app.schemas.specialties import SpecialtyList, SpecialtyOut


def list_specialties() -> SpecialtyList:
    data = get_medisina().call(ops.LIST_SPECIALTIES) or {}
    items = sorted(
        data.get("specialties") or [],
        key=lambda s: (s.get("displayOrder") is None, s.get("displayOrder") or 0, s["specialtyName"]),
    )
    return SpecialtyList(specialties=[
        SpecialtyOut(
            specialty_id=int(s["specialtyId"]),
            name=s["specialtyName"],
            icon_url=s.get("iconUrl"),
            display_order=None if s.get("displayOrder") is None else int(s["displayOrder"]),
        )
        for s in items
    ])
