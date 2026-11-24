"""Input and output shapes for clients.

Deserialization = turning incoming JSON into a validated Python object (ClientCreate, ClientUpdate).
Serialization   = turning a database row into the JSON we choose to send back (ClientOut).
Field rules live in app/validate.py.
"""
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from app.validate import (
    ClientSource,
    Dob,
    Email,
    InputModel,
    Name,
    OptionalName,
    OptionalReferralCode,
    Phone,
)


class ClientCreate(InputModel):
    """Required: phone, first_name, email, dob, source. Optional: last_name, referral_code."""
    phone: Phone = Field(examples=["+919876543210"])
    first_name: Name = Field(examples=["Asha"])
    last_name: OptionalName = None
    dob: Dob = Field(examples=["1995-06-15"])
    email: Email = Field(examples=["asha@example.com"])
    source: ClientSource
    referral_code: OptionalReferralCode = Field(default=None, examples=["PARTNERX"])


class ClientUpdate(InputModel):
    """PATCH: send only the fields you want to change.

    first_name, email and dob are required on a client, so they can be changed
    but not cleared (null is rejected). last_name can be cleared with null.

    phone, source and referral_code are NOT editable here on purpose:
    - phone is the login identity; changing it needs its own OTP flow.
    - referral attribution set after signup is a fraud vector.
    """
    first_name: Name = None   # default None = "not sent"; an explicit null is rejected
    last_name: OptionalName = None
    dob: Dob = None
    email: Email = None


class ClientOut(BaseModel):
    """What the API returns. Internal columns are not exposed."""
    id: UUID
    phone: str
    first_name: Optional[str]
    last_name: Optional[str]
    dob: Optional[date]
    email: Optional[str]
    source: str
    phone_verified_at: Optional[datetime] = Field(exclude=True)  # used, not shown
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def phone_verified(self) -> bool:
        return self.phone_verified_at is not None


# Columns we read from the DB. Explicit list instead of "*" so new
# sensitive columns are never leaked by accident.
CLIENT_COLUMNS = (
    "id,phone,first_name,last_name,dob,email,source,"
    "phone_verified_at,created_at,updated_at"
)