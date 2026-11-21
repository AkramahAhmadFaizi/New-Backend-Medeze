"""HTTP layer for coupons: URLs, status codes, request/response models. No DB code here."""
from fastapi import APIRouter

from app.schemas.coupons import CouponCheck, CouponCheckOut
from app.services import coupons as service

router = APIRouter(prefix="/coupons", tags=["coupons"])


@router.post(
    "/check",
    response_model=CouponCheckOut,
    summary="Check a coupon and preview the discounted price",
    responses={
        404: {"description": "coupon_not_found or client_not_found"},
        422: {"description": "coupon_inactive, coupon_not_started, coupon_expired, "
                             "below_min_amount, wrong_therapist, first_session_only, "
                             "coupon_exhausted, client_limit_reached, validation_error"},
    },
)
def check_coupon(body: CouponCheck):
    """Read-only. Does not reserve the coupon; booking does that later."""
    return service.check_coupon(body)
