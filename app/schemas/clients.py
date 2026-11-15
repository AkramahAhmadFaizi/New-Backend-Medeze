"""Input and output shapes for clients.

Deserialization = turning incoming JSON into a validated Python object (ClientCreate, ClientUpdate).
Serialization   = turning a database row into the JSON we choose to send back (ClientOut).
"""
import re
from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

# Same rule as the DB check constraint on clients.phone
E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
MIN_DOB = date(1900, 1, 2)  # DB rule: dob > 1900-01-01

Source = Literal["match_form", "whatsapp", "web"]


def _clean_name(v):
    if v is None:
        return None
    v = " ".join(v.split())  # trim + collapse inner whitespace
    return v or None  # "" -> None


def _check_dob(v):
    if v is None:
        return None
    if v < MIN_DOB:
        raise ValueError("dob must be after 1900-01-01")
    if v > date.today():
        raise ValueError("dob cannot be in the future")
    return v


class _Input(BaseModel):
    # forbid = reject unknown fields, e.g. a client sending "phone_verified_at"
    model_config = ConfigDict(extra="forbid")


class ClientCreate(_Input):
    phone: str = Field(examples=["+919876543210"])
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    dob: Optional[date] = None
    email: Optional[EmailStr] = None
    source: Source
    referral_code: Optional[str] = Field(default=None, examples=["PARTNERX"])

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, v):
        if not isinstance(v, str):
            raise ValueError("phone must be a string")
        v = re.sub(r"[\s\-()]", "", v)  # "+91 98765-43210" -> "+919876543210"
        if not E164.match(v):
            raise ValueError("phone must be international format, e.g. +919876543210")
        return v

    _names = field_validator("first_name", "last_name", mode="before")(_clean_name)
    _dob = field_validator("dob")(_check_dob)

    @field_validator("email")
    @classmethod
    def lower_email(cls, v):
        return v.lower() if v else v

    @field_validator("referral_code", mode="before")
    @classmethod
    def normalize_code(cls, v):
        if v is None:
            return None
        v = str(v).strip().upper()
        return v or None


class ClientUpdate(_Input):
    """PATCH: send only the fields you want to change. Send null to clear a field.

    phone, source and referral_code are NOT editable here on purpose:
    - phone is the login identity; changing it needs its own OTP flow.
    - referral attribution set after signup is a fraud vector.
    """
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    dob: Optional[date] = None
    email: Optional[EmailStr] = None

    _names = field_validator("first_name", "last_name", mode="before")(_clean_name)
    _dob = field_validator("dob")(_check_dob)

    @field_validator("email")
    @classmethod
    def lower_email(cls, v):
        return v.lower() if v else v


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