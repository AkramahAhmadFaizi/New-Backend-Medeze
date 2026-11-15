"""Unit tests for app/validate.py. No database needed. Run:  pytest -v"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

import pytest
from pydantic import ValidationError, model_validator

from app.validate import (
    ClientSource, CouponCode, DiscountType, Dob, Email, InputModel, Money, Name,
    OptionalEmail, OptionalName, Phone, PositiveMoney, ReferralCode, SessionMinutes,
    TagList, Timestamp, Url, ensure_end_after_start, ensure_valid_percent,
)


def model(**fields):
    """Build a throwaway InputModel with the given field types."""
    return type("M", (InputModel,), {"__annotations__": fields})


# ---------- Phone ----------
@pytest.mark.parametrize("raw,clean", [
    ("+919876543210", "+919876543210"),
    ("+91 98765 43210", "+919876543210"),
    ("+91-98765-43210", "+919876543210"),
    ("+1 (415) 555-0100", "+14155550100"),
])
def test_phone_normalizes(raw, clean):
    assert model(p=Phone)(p=raw).p == clean


@pytest.mark.parametrize("bad", ["9876543210", "+0123456789", "+91", "+91abc", 919876543210, ""])
def test_phone_rejects(bad):
    with pytest.raises(ValidationError):
        model(p=Phone)(p=bad)


# ---------- Email ----------
def test_email_lowercased():
    assert model(e=Email)(e="Asha@Example.COM").e == "asha@example.com"


def test_optional_email_blank_becomes_none():
    M = model(e=OptionalEmail)
    assert M(e="").e is None and M(e=None).e is None


def test_email_rejects_garbage():
    with pytest.raises(ValidationError):
        model(e=Email)(e="not-an-email")


# ---------- Names ----------
def test_name_collapses_spaces():
    assert model(n=Name)(n="  Asha   Rao ").n == "Asha Rao"


def test_optional_name_blank_is_none():
    assert model(n=OptionalName)(n="   ").n is None


def test_required_name_rejects_blank_and_too_long():
    with pytest.raises(ValidationError):
        model(n=Name)(n="   ")
    with pytest.raises(ValidationError):
        model(n=Name)(n="x" * 101)


# ---------- Dob ----------
def test_dob_rules():
    M = model(d=Dob)
    assert M(d="1995-06-15").d == date(1995, 6, 15)
    for bad in ["1900-01-01", (date.today() + timedelta(days=1)).isoformat(), "15-06-1995"]:
        with pytest.raises(ValidationError):
            M(d=bad)


# ---------- Timestamps ----------
def test_timestamp_requires_timezone():
    M = model(t=Timestamp)
    assert M(t="2026-11-20T10:00:00+05:30").t.utcoffset() is not None
    with pytest.raises(ValidationError):
        M(t="2026-11-20T10:00:00")


def test_end_after_start():
    class Slot(InputModel):
        start_at: Timestamp
        end_at: Timestamp

        @model_validator(mode="after")
        def _check(self):
            ensure_end_after_start(self.start_at, self.end_at)
            return self

    Slot(start_at="2026-11-20T10:00:00+05:30", end_at="2026-11-20T10:50:00+05:30")
    with pytest.raises(ValidationError):
        Slot(start_at="2026-11-20T10:00:00+05:30", end_at="2026-11-20T10:00:00+05:30")


# ---------- Codes ----------
def test_codes_uppercased_and_length_checked():
    assert model(c=ReferralCode)(c=" partnerx ").c == "PARTNERX"
    assert model(c=CouponCode)(c="welcome20").c == "WELCOME20"
    for bad in ["abc", "x" * 21]:
        with pytest.raises(ValidationError):
            model(c=ReferralCode)(c=bad)


# ---------- Money ----------
def test_money():
    assert model(m=Money)(m="1500.50").m == Decimal("1500.50")
    for bad in ["-1", "1.234", "100000000.00"]:
        with pytest.raises(ValidationError):
            model(m=Money)(m=bad)
    with pytest.raises(ValidationError):
        model(m=PositiveMoney)(m="0")


def test_percent_cap():
    class Coupon(InputModel):
        discount_type: DiscountType
        discount_value: PositiveMoney

        @model_validator(mode="after")
        def _check(self):
            ensure_valid_percent(self.discount_type, self.discount_value)
            return self

    Coupon(discount_type="percent", discount_value="20")
    Coupon(discount_type="flat", discount_value="300")
    with pytest.raises(ValidationError):
        Coupon(discount_type="percent", discount_value="120")


# ---------- Misc ----------
def test_url():
    assert model(u=Url)(u="https://cdn.example.com/a.jpg").u == "https://cdn.example.com/a.jpg"
    for bad in ["ftp://x.com", "not a url", "javascript:alert(1)"]:
        with pytest.raises(ValidationError):
            model(u=Url)(u=bad)


def test_taglist_cleans_and_dedupes():
    assert model(t=TagList)(t=[" Hindi ", "English", "hindi"]).t == ["Hindi", "English"]
    with pytest.raises(ValidationError):
        model(t=TagList)(t=["ok", "   "])


def test_session_minutes():
    model(s=SessionMinutes)(s=50)
    for bad in [9, 241]:
        with pytest.raises(ValidationError):
            model(s=SessionMinutes)(s=bad)


def test_literals_and_extra_fields():
    M = model(source=ClientSource)
    M(source="web")
    with pytest.raises(ValidationError):
        M(source="tiktok")
    with pytest.raises(ValidationError):
        M(source="web", phone_verified_at="2026-01-01T00:00:00Z")  # unknown field