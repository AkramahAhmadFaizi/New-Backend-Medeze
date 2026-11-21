"""Input and output shapes for coupons.

CouponCheck    = what the caller sends to ask "can this client use this coupon?"
CouponCheckOut = the answer: the discount and the price after it.
CouponRow      = internal: one row of public.coupons, read by the service. Never returned.
Field rules live in app/validate.py.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.validate import CouponCode, DiscountType, InputModel, PositiveMoney


class CouponCheck(InputModel):
    code: CouponCode = Field(examples=["WELCOME20"])
    client_id: UUID = Field(examples=["11111111-1111-1111-1111-111111111111"])
    amount: PositiveMoney = Field(
        description="Session price before discount (INR).", examples=["1500.00"]
    )
    therapist_id: Optional[UUID] = Field(
        default=None,
        description="Needed only if the coupon is limited to one therapist.",
        examples=[None],
    )


class CouponCheckOut(BaseModel):
    """Read-only result. Nothing is reserved; booking reserves the coupon later."""
    valid: bool = True
    code: str
    discount_type: DiscountType
    discount_value: Decimal
    amount: Decimal
    discount_amount: Decimal
    final_amount: Decimal


class CouponRow(BaseModel):
    id: UUID
    code: str
    discount_type: DiscountType
    discount_value: Decimal
    max_discount: Optional[Decimal]
    min_amount: Decimal
    valid_from: datetime
    valid_to: Optional[datetime]
    max_uses_total: Optional[int]
    max_uses_per_client: int
    first_session_only: bool
    therapist_id: Optional[UUID]
    is_active: bool


# Explicit column list (same reason as CLIENT_COLUMNS: no accidental leaks).
COUPON_COLUMNS = (
    "id,code,discount_type,discount_value,max_discount,min_amount,valid_from,"
    "valid_to,max_uses_total,max_uses_per_client,first_session_only,therapist_id,is_active"
)
