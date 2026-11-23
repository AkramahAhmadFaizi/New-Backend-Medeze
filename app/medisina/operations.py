"""Registry of every Medisina endpoint this app calls.

Services never type a Medisina URL themselves: they pass one of these to
client.call(). That way `python portal-backend/contract.py check` can check
every endpoint we depend on against the live contract in one go.

To call a new Medisina endpoint:
  1. Find it in the contract: `python portal-backend/contract.py show "/doctors/{id}"`
  2. Add an Op below and add it to ALL_OPS.
  3. Run `python portal-backend/contract.py check` to confirm it matches.

Example:
    SEARCH_DOCTORS = Op("GET", "/doctors/search", query=("q", "city", "limit", "offset"))
    GET_DOCTOR     = Op("GET", "/doctors/{id}")
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Op:
    method: str                      # "GET", "POST", ...
    path: str                        # exactly as in the contract, e.g. "/doctors/{id}"
    auth: bool = True                # send Authorization: Bearer <token>
    query: tuple[str, ...] = field(default=())  # query params we send (checked against the contract)


# ---- Auth (used internally by client.py) ----
LOGIN = Op("POST", "/auth/login", auth=False)
REFRESH = Op("POST", "/auth/refresh", auth=False)

# ---- Specialties ----
LIST_SPECIALTIES = Op("GET", "/specialties")

# ---- Doctors ----
GET_DOCTOR = Op("GET", "/doctors/{id}")
SEARCH_DOCTORS = Op(
    "GET",
    "/doctors/search",
    query=("q", "specialtyId", "city", "language", "limit", "offset"),
)

# ---- Appointments ----
GET_AVAILABLE_SLOTS = Op(
    "GET",
    "/appointments/doctors/{id}/available-slots",
    query=("date",),
)

CREATE_APPOINTMENT = Op("POST", "/appointments")
GET_APPOINTMENT = Op("GET", "/appointments/{id}")
CANCEL_APPOINTMENT = Op("DELETE", "/appointments/{id}")

# ---- Add new operations below, one per Medisina endpoint you need ----


ALL_OPS: list[Op] = [
    LOGIN, REFRESH, LIST_SPECIALTIES, GET_DOCTOR, SEARCH_DOCTORS,
    GET_AVAILABLE_SLOTS, CREATE_APPOINTMENT, GET_APPOINTMENT, CANCEL_APPOINTMENT,
]
