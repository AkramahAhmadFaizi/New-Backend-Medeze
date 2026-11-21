"""Unit tests for coupon math and input validation (no DB needed)."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.coupons import CouponCheck, CouponRow
from app.services.coupons import compute_discount


def coupon(**kw) -> CouponRow:
    base = dict(
        id=uuid4(), code="X", discount_type="percent", discount_value=Decimal("20"),
        max_discount=None, min_amount=Decimal("0"),
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc), valid_to=None,
        max_uses_total=None, max_uses_per_client=1, first_session_only=False,
        therapist_id=None, is_active=True,
    )
    base.update(kw)
    return CouponRow(**base)


@pytest.mark.parametrize("kw, amount, expected", [
    ({}, "1500", "300.00"),                                    # plain percent
    ({"max_discount": Decimal("250")}, "1500", "250.00"),      # percent capped
    ({"discount_value": Decimal("12.5")}, "99.99", "12.50"),   # rounds half up
    ({"discount_type": "flat", "discount_value": Decimal("200")}, "1500", "200.00"),
    ({"discount_type": "flat", "discount_value": Decimal("200")}, "150", "150.00"),  # never below 0
])
def test_compute_discount(kw, amount, expected):
    assert compute_discount(coupon(**kw), Decimal(amount)) == Decimal(expected)


def test_check_normalizes_code():
    c = CouponCheck(code="  welcome20 ", client_id=uuid4(), amount="1500")
    assert c.code == "WELCOME20"


@pytest.mark.parametrize("bad", [
    {"amount": "0"},
    {"amount": "-5"},
    {"amount": "1.234"},
    {"client_id": "not-a-uuid"},
    {"discount_amount": "1500"},  # unknown field
])
def test_check_rejects(bad):
    body = {"code": "WELCOME20", "client_id": str(uuid4()), "amount": "1500"} | bad
    with pytest.raises(ValidationError):
        CouponCheck(**body)
