"""Business logic for coupons. Routers call these; these call Supabase.

check_coupon() is READ-ONLY: it answers "would this coupon work right now?"
and computes the price. It does not reserve anything. The real guarantee
against over-use is the DB trigger on coupon_redemptions at booking time.
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from app.db import get_supabase
from app.errors import AppError
from app.schemas.coupons import COUPON_COLUMNS, CouponCheck, CouponCheckOut, CouponRow

CENT = Decimal("0.01")

# Sessions that count as "the client already had a session" for first_session_only.
_BOOKED_STATUSES = ("confirmed", "completed", "no_show")


def _reject(code: str, message: str) -> AppError:
    return AppError(422, code, message)


def _get_coupon(code: str) -> CouponRow:
    res = (
        get_supabase().table("coupons")
        .select(COUPON_COLUMNS).eq("code", code).limit(1).execute()
    )
    if not res.data:
        raise AppError(404, "coupon_not_found", f"Coupon '{code}' does not exist.")
    return CouponRow.model_validate(res.data[0])


def _client_exists(client_id: str) -> bool:
    res = get_supabase().table("clients").select("id").eq("id", client_id).limit(1).execute()
    return bool(res.data)


def _active_redemptions(coupon_id: str, client_id: str | None = None) -> int:
    """Reserved + used redemptions. Released ones give the use back."""
    q = (
        get_supabase().table("coupon_redemptions")
        .select("id", count="exact", head=True)
        .eq("coupon_id", coupon_id).neq("status", "released")
    )
    if client_id:
        q = q.eq("client_id", client_id)
    return q.execute().count or 0


def _has_booked_session(client_id: str) -> bool:
    res = (
        get_supabase().table("sessions")
        .select("id").eq("client_id", client_id)
        .in_("status", list(_BOOKED_STATUSES)).limit(1).execute()
    )
    return bool(res.data)


def compute_discount(coupon: CouponRow, amount: Decimal) -> Decimal:
    """Pure math, no DB. Never discounts more than the amount itself."""
    if coupon.discount_type == "percent":
        discount = amount * coupon.discount_value / 100
        if coupon.max_discount is not None:
            discount = min(discount, coupon.max_discount)
    else:  # flat
        discount = coupon.discount_value
    return min(discount, amount).quantize(CENT, rounding=ROUND_HALF_UP)


def check_coupon(data: CouponCheck) -> CouponCheckOut:
    coupon = _get_coupon(data.code)
    client_id = str(data.client_id)
    now = datetime.now(timezone.utc)

    # Cheapest checks first; DB counts last.
    if not coupon.is_active:
        raise _reject("coupon_inactive", "This coupon is no longer active.")
    if now < coupon.valid_from:
        raise _reject("coupon_not_started", "This coupon is not valid yet.")
    if coupon.valid_to is not None and now >= coupon.valid_to:
        raise _reject("coupon_expired", "This coupon has expired.")
    if data.amount < coupon.min_amount:
        raise _reject(
            "below_min_amount",
            f"This coupon needs a minimum amount of {coupon.min_amount}.",
        )
    if coupon.therapist_id is not None and data.therapist_id != coupon.therapist_id:
        raise _reject("wrong_therapist", "This coupon is not valid for this therapist.")

    if not _client_exists(client_id):
        raise AppError(404, "client_not_found", "Client not found.")
    if coupon.first_session_only and _has_booked_session(client_id):
        raise _reject("first_session_only", "This coupon is only valid on a first session.")

    coupon_id = str(coupon.id)
    if coupon.max_uses_total is not None and _active_redemptions(coupon_id) >= coupon.max_uses_total:
        raise _reject("coupon_exhausted", "This coupon has been fully redeemed.")
    if _active_redemptions(coupon_id, client_id) >= coupon.max_uses_per_client:
        raise _reject("client_limit_reached", "You have already used this coupon.")

    amount = data.amount.quantize(CENT)
    discount = compute_discount(coupon, amount)
    return CouponCheckOut(
        code=coupon.code,
        discount_type=coupon.discount_type,
        discount_value=coupon.discount_value.quantize(CENT),
        amount=amount,
        discount_amount=discount,
        final_amount=amount - discount,
    )
