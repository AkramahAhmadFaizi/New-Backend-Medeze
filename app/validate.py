"""Shared input validation for the whole API (DRY).

Every schema imports its field types from here instead of re-writing rules.
Each rule mirrors a constraint in the database schema, so bad input is
rejected with a clear 422 before it ever reaches Supabase.

Usage in a schema:
    from app.validate import InputModel, Phone, OptionalName, ClientSource

    class ClientCreate(InputModel):
        phone: Phone
        first_name: OptionalName = None
        source: ClientSource
"""
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    StringConstraints,
    TypeAdapter,
)

# =====================================================================
# Base model for ALL request bodies
# =====================================================================
class InputModel(BaseModel):
    """Rejects unknown fields, so callers cannot set server-only columns
    such as phone_verified_at, status or final_amount."""
    model_config = ConfigDict(extra="forbid")


# =====================================================================
# Small reusable cleaners
# =====================================================================
def _blank_to_none(v):
    """'' or '   ' -> None, so optional fields can be cleared with an empty string."""
    if isinstance(v, str) and not v.strip():
        return None
    return v


def _collapse_spaces(v):
    """'  Asha   Rao ' -> 'Asha Rao'."""
    return " ".join(v.split()) if isinstance(v, str) else v


def _upper_strip(v):
    return v.strip().upper() if isinstance(v, str) else v


# =====================================================================
# Phone  (DB: ^\+[1-9][0-9]{7,14}$ on clients, therapists, otp_verifications)
# =====================================================================
E164_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")


def _normalize_phone(v):
    if not isinstance(v, str):
        raise ValueError("phone must be a string")
    v = re.sub(r"[\s\-().]", "", v)  # "+91 98765-43210" -> "+919876543210"
    if not E164_PATTERN.match(v):
        raise ValueError("phone must be international format, e.g. +919876543210")
    return v


Phone = Annotated[str, BeforeValidator(_normalize_phone)]
OptionalPhone = Annotated[Optional[Phone], BeforeValidator(_blank_to_none)]

# =====================================================================
# Email  (stored lowercase)
# =====================================================================
Email = Annotated[EmailStr, AfterValidator(lambda v: v.lower())]
OptionalEmail = Annotated[Optional[Email], BeforeValidator(_blank_to_none)]

# =====================================================================
# Names / short text
# =====================================================================
Name = Annotated[
    str,
    BeforeValidator(_collapse_spaces),
    StringConstraints(min_length=1, max_length=100),
]
OptionalName = Annotated[Optional[Name], BeforeValidator(_blank_to_none)]

# Free text such as therapists.about or sessions.concern
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
OptionalLongText = Annotated[Optional[LongText], BeforeValidator(_blank_to_none)]

# =====================================================================
# Dates and times
# =====================================================================
MIN_DOB = date(1900, 1, 2)  # DB: dob > 1900-01-01


def _check_dob(v: date) -> date:
    if v < MIN_DOB:
        raise ValueError("dob must be after 1900-01-01")
    if v > date.today():
        raise ValueError("dob cannot be in the future")
    return v


Dob = Annotated[date, AfterValidator(_check_dob)]
OptionalDob = Annotated[Optional[Dob], BeforeValidator(_blank_to_none)]

# Timestamps MUST carry a timezone ("2026-11-20T10:00:00+05:30").
# A naive "2026-11-20T10:00:00" is ambiguous for timestamptz columns.
Timestamp = AwareDatetime


def ensure_end_after_start(start, end) -> None:
    """Call from a model_validator. DB: end_at > start_at."""
    if start is not None and end is not None and end <= start:
        raise ValueError("end_at must be after start_at")

# =====================================================================
# Codes  (DB: stored uppercase)
# =====================================================================
ReferralCode = Annotated[
    str, BeforeValidator(_upper_strip), StringConstraints(min_length=4, max_length=20)
]  # DB: upper(code) and length 4..20
OptionalReferralCode = Annotated[Optional[ReferralCode], BeforeValidator(_blank_to_none)]

CouponCode = Annotated[
    str, BeforeValidator(_upper_strip), StringConstraints(min_length=1, max_length=50)
]  # DB: upper(code)
OptionalCouponCode = Annotated[Optional[CouponCode], BeforeValidator(_blank_to_none)]

# =====================================================================
# Money  (DB: numeric(10,2) -> max 99,999,999.99)
# =====================================================================
Money = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]


def ensure_valid_percent(discount_type, value) -> None:
    """Call from a model_validator. DB: percent discounts must be <= 100."""
    if discount_type == "percent" and value is not None and value > 100:
        raise ValueError("percent discount cannot exceed 100")

# =====================================================================
# Misc
# =====================================================================
_http_url = TypeAdapter(HttpUrl)


def _check_url(v: str) -> str:
    _http_url.validate_python(v)  # raises if not a valid http(s) URL
    return v                      # keep the caller's exact string


Url = Annotated[str, AfterValidator(_check_url)]
OptionalUrl = Annotated[Optional[Url], BeforeValidator(_blank_to_none)]


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        if i.lower() not in seen:
            seen.add(i.lower())
            out.append(i)
    return out


# therapists.languages / specialties (DB: jsonb array)
TagList = Annotated[list[Name], Field(max_length=50), AfterValidator(_dedupe)]

SessionMinutes = Annotated[int, Field(ge=10, le=240)]  # DB: between 10 and 240

# OTP code typed by the user: digits only
OtpCode = Annotated[
    str,
    BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v),
    StringConstraints(pattern=r"^[0-9]{4,10}$"),
]

# =====================================================================
# Allowed values  (each mirrors a CHECK constraint in the schema)
# =====================================================================
ClientSource = Literal["match_form", "whatsapp", "web"]
OtpChannel = Literal["sms", "whatsapp"]
OtpProvider = Literal["msg91", "twilio", "fake", "2factor"]  # mirrors DB check (twilio/msg91 allowed by DB, not implemented)
OtpStatus = Literal["sent", "verified", "failed", "expired"]
ReferralOwnerType = Literal["client", "therapist", "partner"]
DiscountType = Literal["percent", "flat"]
ReferrerRewardType = Literal["percent", "flat", "credit", "free_session"]
SlotStatus = Literal["open", "held", "booked", "blocked"]
SessionStatus = Literal["pending_payment", "confirmed", "completed", "cancelled", "no_show"]
PaymentStatus = Literal["created", "paid", "failed", "refunded"]
RedemptionStatus = Literal["reserved", "used", "released"]
ReferralStatus = Literal["pending", "qualified", "rewarded"]
ConsentPurpose = Literal["terms", "privacy", "whatsapp_messages", "health_data"]