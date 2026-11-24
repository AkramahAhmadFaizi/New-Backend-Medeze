# Phone OTP: 2Factor provider (Twilio removed), India-only, daily cap. Run from the project folder.
$ErrorActionPreference = "Stop"
if (-not (Test-Path .\app\main.py)) { throw "Wrong folder: cd into the project folder first" }
$sha = [Security.Cryptography.SHA256]::Create()
function Get-NormHash($path) {
  $t = [IO.File]::ReadAllText($path).Replace("`r`n", "`n").TrimEnd("`n")
  -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($t)) | ForEach-Object { $_.ToString("x2") })
}
$skipped = @()
function Update-File($rel, $expectedHash, $text) {
  $p = Join-Path $PWD.Path $rel
  if ($expectedHash -ne "" -and (Test-Path $p) -and ((Get-NormHash $p) -ne $expectedHash)) {
    Write-Host "SKIPPED $rel (changed since phase 1 - not overwritten)" -ForegroundColor Yellow
    $script:skipped += $rel; return
  }
  New-Item -ItemType Directory -Force -Path (Split-Path $p) | Out-Null
  [IO.File]::WriteAllText($p, $text)
  Write-Host "updated $rel"
}

Update-File "app/config.py" "a93cc75836cfa0c886037eb1bd2b6cdaff352fb5578c7f4d2c85ba72b889f649" @'
"""Loads settings from the .env file and validates them at startup."""
from functools import lru_cache
from typing import Literal, Optional

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ---- Supabase ----
    supabase_url: str
    supabase_secret_key: SecretStr  # SecretStr hides the value in logs/prints

    # ---- App ----
    app_env: Literal["local", "staging", "production"] = "local"

    # ---- OTP provider: switch with OTP_PROVIDER in .env, no code change ----
    otp_provider: Literal["fake", "2factor"] = "fake"
    twofactor_api_key: Optional[SecretStr] = None
    twofactor_template_name: Optional[str] = None   # DLT template name in the 2Factor dashboard

    # ---- OTP rules ----
    otp_ttl_seconds: int = 600                # code valid for 10 min
    otp_max_sends_per_phone: int = 3          # per phone ...
    otp_phone_window_minutes: int = 10        # ... in this many minutes
    otp_max_sends_per_ip_per_hour: int = 10
    otp_max_attempts: int = 5                 # wrong codes before the OTP is burned
    otp_max_sends_per_day: int = 50           # GLOBAL budget guard (all phones, rolling 24h)
    otp_allowed_country_codes: str = "+91"    # comma-separated, e.g. "+91" or "+91,+971"

    # ---- Token issued after a successful OTP ----
    otp_token_secret: SecretStr
    otp_token_ttl_seconds: int = 900          # 15 min

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("supabase_url")
    @classmethod
    def check_url(cls, v: str) -> str:
        v = v.rstrip("/")
        if not v.startswith("https://") or "/rest/v1" in v:
            raise ValueError(
                "SUPABASE_URL must be the project URL, e.g. "
                "https://abcd.supabase.co (without /rest/v1)"
            )
        return v

    @field_validator("supabase_secret_key")
    @classmethod
    def check_key(cls, v: SecretStr) -> SecretStr:
        if v.get_secret_value().startswith("sb_publishable_"):
            raise ValueError(
                "That is the PUBLISHABLE key. The backend needs the SECRET key "
                "(sb_secret_...) from Project Settings -> API Keys."
            )
        return v

    @field_validator("otp_token_secret")
    @classmethod
    def check_token_secret(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError(
                "OTP_TOKEN_SECRET must be at least 32 characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return v

    @property
    def otp_country_codes(self) -> list[str]:
        return [c.strip() for c in self.otp_allowed_country_codes.split(",") if c.strip()]

    @model_validator(mode="after")
    def check_otp_provider(self):
        if self.otp_provider == "2factor" and not self.twofactor_api_key:
            raise ValueError("OTP_PROVIDER=2factor needs: TWOFACTOR_API_KEY")
        if self.app_env == "production" and self.otp_provider == "fake":
            raise ValueError("OTP_PROVIDER=fake is not allowed when APP_ENV=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
'@

Update-File "app/validate.py" "cdbdb0aa80095a23930b53bb22a307a0e41e3f7bd31f611bd95841a50561ea7f" @'
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
'@

Update-File "app/integrations/otp_provider.py" "29a26916e5f2e0978a96fd1c96b1e1fc1c8d22ea13e8f96c2af0771f7a896b3c" @'
"""OTP providers (adapter pattern).

Services call OtpProvider.send / .check and never talk to an SMS vendor directly.
Providers: fake (tests/local) and 2factor (real SMS, India).
Switching = change OTP_PROVIDER in .env. Adding another provider later = one new class.

check() returns one of:
    "approved" - code correct
    "pending"  - code wrong, user may try again
    "expired"  - no active code (expired, already used, or provider gave up)
    "failed"   - provider refused (e.g. too many attempts on its side)
"""
import hmac
import logging
import secrets
import time
import uuid
from functools import lru_cache
from urllib.parse import quote
from typing import Literal, Optional, Protocol

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

CheckResult = Literal["approved", "pending", "expired", "failed"]


class OtpProviderError(Exception):
    """Provider unreachable or returned an unexpected error."""


class OtpProvider(Protocol):
    name: str

    def send(self, phone: str, channel: str) -> str:
        """Send a code. Returns the provider's request id."""

    def check(self, phone: str, code: str, request_id: Optional[str]) -> CheckResult:
        """Check a code the user typed."""


# ---------------------------------------------------------------------
# Fake: for local development and tests. Prints the code in the terminal.
# ---------------------------------------------------------------------
class FakeOtpProvider:
    name = "fake"

    def __init__(self, ttl_seconds: int = 600):
        self._ttl = ttl_seconds
        self._codes: dict[str, tuple[str, float]] = {}  # phone -> (code, expires)

    def send(self, phone: str, channel: str) -> str:
        code = f"{secrets.randbelow(10**6):06d}"
        self._codes[phone] = (code, time.monotonic() + self._ttl)
        print(f"\n===== FAKE OTP ({channel}) for {phone}: {code} =====\n", flush=True)
        return f"fake-{uuid.uuid4().hex}"

    def check(self, phone: str, code: str, request_id: Optional[str]) -> CheckResult:
        entry = self._codes.get(phone)
        if entry is None:
            return "expired"
        expected, expires = entry
        if time.monotonic() > expires:
            self._codes.pop(phone, None)
            return "expired"
        if hmac.compare_digest(code, expected):  # constant-time compare
            self._codes.pop(phone, None)          # one-time use
            return "approved"
        return "pending"

    def last_code(self, phone: str) -> Optional[str]:
        """Tests only."""
        entry = self._codes.get(phone)
        return entry[0] if entry else None


# ---------------------------------------------------------------------
# 2Factor.in: Indian provider. It generates and checks
# the code itself and returns a session id. Pay per delivered OTP.
#   send:   GET /API/V1/{key}/SMS/{91XXXXXXXXXX}/AUTOGEN[/{template}]
#           -> {"Status": "Success", "Details": "<session_id>"}
#   verify: GET /API/V1/{key}/SMS/VERIFY/{session_id}/{code}
#           -> Details "OTP Matched" | "OTP Mismatch" | "OTP Expired"
# The API key is in the URL path, so errors never include the URL.
# ---------------------------------------------------------------------
class TwoFactorProvider:
    name = "2factor"
    BASE = "https://2factor.in/API/V1"

    def __init__(self, api_key: str, template_name: Optional[str] = None,
                 transport: Optional[httpx.BaseTransport] = None):
        self._key = api_key
        self._template = template_name
        self._http = httpx.Client(timeout=10.0, transport=transport)

    def _get(self, path: str) -> tuple[int, dict]:
        try:
            r = self._http.get(f"{self.BASE}/{quote(self._key, safe='')}/{path}")
        except httpx.HTTPError:
            raise OtpProviderError("2Factor unreachable") from None  # no details: URL holds the key
        try:
            body = r.json()
        except ValueError:
            raise OtpProviderError(f"2Factor returned non-JSON (HTTP {r.status_code})") from None
        return r.status_code, body if isinstance(body, dict) else {}

    def send(self, phone: str, channel: str) -> str:
        number = phone.lstrip("+")  # 2Factor expects 91XXXXXXXXXX
        path = f"SMS/{number}/AUTOGEN"
        if self._template:
            path += f"/{quote(self._template, safe='')}"
        status, body = self._get(path)
        if body.get("Status") != "Success" or not body.get("Details"):
            detail = str(body.get("Details", ""))[:120]
            raise OtpProviderError(f"2Factor send failed (HTTP {status}): {detail}")
        return str(body["Details"])

    def check(self, phone: str, code: str, request_id: Optional[str]) -> CheckResult:
        if not request_id:
            return "expired"
        status, body = self._get(f"SMS/VERIFY/{quote(request_id, safe='')}/{code}")
        details = str(body.get("Details", "")).lower()
        if "expired" in details:
            return "expired"
        if "mismatch" in details:
            return "pending"
        if body.get("Status") == "Success" and "matched" in details:
            return "approved"
        if status >= 500:
            raise OtpProviderError(f"2Factor check failed (HTTP {status})")
        return "failed"  # unknown session or other error: treat as burned


@lru_cache
def get_otp_provider() -> OtpProvider:
    s = get_settings()
    if s.otp_provider == "2factor":
        return TwoFactorProvider(s.twofactor_api_key.get_secret_value(), s.twofactor_template_name)
    return FakeOtpProvider(ttl_seconds=s.otp_ttl_seconds)
'@

Update-File "app/services/otp.py" "0c65b856c77aae02e5cec356ca5ef1bc6b04b49fe1c67e46e81acb1cec17740e" @'
"""Phone OTP business logic: rate limits, audit rows, status mapping, token."""
import ipaddress
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import get_settings
from app.db import get_supabase
from app.errors import AppError
from app.integrations.otp_provider import OtpProviderError, get_otp_provider
from app.tokens import issue_phone_token

TABLE = "otp_verifications"
# Same answer whether or not the phone belongs to a client: never leak who is registered.
SEND_MESSAGE = "If the number is valid, a verification code has been sent."


def _invalid() -> AppError:
    # One generic message for wrong / expired / burned codes: don't help guessers.
    return AppError(400, "invalid_code", "The code is invalid or has expired.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def _clean_ip(ip: Optional[str]) -> Optional[str]:
    """Column type is inet; store only real IP addresses."""
    try:
        return str(ipaddress.ip_address(ip)) if ip else None
    except ValueError:
        return None


def _count_since(column: Optional[str], value: Optional[str], since: datetime) -> int:
    """Rows created since `since`. column=None counts all phones (global)."""
    q = get_supabase().table(TABLE).select("id", count="exact")
    if column:
        q = q.eq(column, value)
    res = q.gte("created_at", since.isoformat()).limit(1).execute()
    return res.count or 0


def _set_status(row_id: str, status: str, **extra) -> None:
    get_supabase().table(TABLE).update({"status": status, **extra}).eq("id", row_id).execute()


def send_otp(phone: str, channel: str, ip: Optional[str]) -> dict:
    s = get_settings()
    now = _now()
    ip = _clean_ip(ip)

    # 0. Only supported countries (we pay per SMS; India only for now)
    if not any(phone.startswith(cc) for cc in s.otp_country_codes):
        raise AppError(422, "unsupported_country", "Phone numbers from this country are not supported yet.")

    # 1. Rate limits (protect users from spam and us from SMS-pumping bills)
    if _count_since("phone", phone, now - timedelta(minutes=s.otp_phone_window_minutes)) >= s.otp_max_sends_per_phone:
        raise AppError(429, "rate_limited", "Too many codes requested. Try again later.")
    if ip and _count_since("ip", ip, now - timedelta(hours=1)) >= s.otp_max_sends_per_ip_per_hour:
        raise AppError(429, "rate_limited", "Too many codes requested. Try again later.")
    # Budget guard: hard cap on SMS across ALL phones in the last 24h
    if _count_since(None, None, now - timedelta(hours=24)) >= s.otp_max_sends_per_day:
        raise AppError(503, "otp_daily_limit", "Verification is temporarily unavailable. Try again later.")

    sb = get_supabase()
    # 2. Only the newest code counts: retire older unused ones
    sb.table(TABLE).update({"status": "expired"}).eq("phone", phone).eq("status", "sent").execute()

    # 3. Ask the provider to send
    provider = get_otp_provider()
    row = {
        "phone": phone,
        "channel": channel,
        "provider": provider.name,
        "expires_at": (now + timedelta(seconds=s.otp_ttl_seconds)).isoformat(),
        "ip": ip,
    }
    try:
        row["provider_request_id"] = provider.send(phone, channel)
        row["status"] = "sent"
    except OtpProviderError:
        row["status"] = "failed"  # still recorded: failed sends count toward limits
        sb.table(TABLE).insert(row).execute()
        raise AppError(502, "otp_send_failed", "Could not send the code. Try again shortly.")

    # 4. Audit row (never contains the code itself)
    sb.table(TABLE).insert(row).execute()
    return {"message": SEND_MESSAGE, "expires_in": s.otp_ttl_seconds}


def verify_otp(phone: str, code: str) -> dict:
    s = get_settings()
    now = _now()
    sb = get_supabase()

    res = (
        sb.table(TABLE)
        .select("id,provider_request_id,attempts,expires_at,status")
        .eq("phone", phone).eq("status", "sent")
        .order("created_at", desc=True).limit(1).execute()
    )
    if not res.data:
        raise _invalid()
    row = res.data[0]

    if _parse_ts(row["expires_at"]) <= now:
        _set_status(row["id"], "expired")
        raise _invalid()
    if row["attempts"] >= s.otp_max_attempts:
        _set_status(row["id"], "failed")
        raise _invalid()

    # Count the attempt BEFORE checking, so brute force is capped even if check fails
    attempts = row["attempts"] + 1
    sb.table(TABLE).update({"attempts": attempts}).eq("id", row["id"]).execute()

    try:
        result = get_otp_provider().check(phone, code, row["provider_request_id"])
    except OtpProviderError:
        raise AppError(502, "otp_check_failed", "Could not check the code. Try again shortly.")

    if result == "approved":
        _set_status(row["id"], "verified", verified_at=now.isoformat())
        updated = (
            sb.table("clients").update({"phone_verified_at": now.isoformat()})
            .eq("phone", phone).execute()
        )
        client_id = updated.data[0]["id"] if updated.data else None
        token, ttl = issue_phone_token(phone, client_id)
        return {
            "verified": True,
            "access_token": token,
            "token_type": "bearer",
            "expires_in": ttl,
            "client_id": client_id,
            "is_new_client": client_id is None,
        }

    if result in ("expired", "failed"):
        _set_status(row["id"], result)
    elif attempts >= s.otp_max_attempts:
        _set_status(row["id"], "failed")
    raise _invalid()
'@

Update-File ".env.example" "fc4c98052a0cd40b70c6a0eac42a9fe666585dbdf11e92ef9b2d30b7bf43706c" @'
# Copy this file to .env and fill in real values. Never commit .env.
# Supabase dashboard -> Project Settings -> Data API  (Project URL)
SUPABASE_URL=https://your-project-ref.supabase.co
# Supabase dashboard -> Project Settings -> API Keys -> Secret key (sb_secret_...)
# SERVER-SIDE ONLY. This key bypasses RLS.
SUPABASE_SECRET_KEY=sb_secret_replace_me

# ---- App ----
APP_ENV=local

# ---- Phone OTP ----
# fake = code is printed in the server terminal (local only, refused when APP_ENV=production)
# 2factor = real SMS via 2Factor.in (India, pay per delivered OTP) -> fill TWOFACTOR_API_KEY
OTP_PROVIDER=fake
# TWOFACTOR_API_KEY=
# TWOFACTOR_TEMPLATE_NAME=      # optional: your DLT-approved template name in 2Factor
# OTP_MAX_SENDS_PER_DAY=50      # budget guard: max SMS per rolling 24h, all users
# OTP_ALLOWED_COUNTRY_CODES=+91

# Signs the token returned by /auth/otp/verify. At least 32 chars. Generate:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
OTP_TOKEN_SECRET=replace_with_generated_secret
'@

Update-File "README.md" "e963c667291bbdb8e0fce38defc00666b249d5de4a1c41853324be75f633970c" @'
# Therapy Platform API (FastAPI + Supabase)

Backend layer between callers (Postman / future frontend) and Supabase.
Status: **phone OTP + clients create/read/update.** No auth yet: local only, do not deploy.

## Request flow
```
HTTP request
  -> routers/   URL + status code + which schema to use     (HTTP layer)
  -> schemas/   validate + normalize input (deserialize)    (Pydantic)
  -> services/  business rules, talks to Supabase           (logic layer)
  -> schemas/   shape the DB row into the response (serialize)
  -> errors.py  any failure becomes {"error": {...}}
```

## Layout
```
app/
  main.py               entry point, wires everything
  config.py             loads + validates .env
  db.py                 one shared Supabase client
  errors.py             consistent error responses, DB error mapping
  validate.py           shared field types + allowed values (all schemas use these)
  schemas/clients.py    ClientCreate, ClientUpdate (input), ClientOut (output)
  services/clients.py   create / get / update logic
  services/otp.py       OTP rate limits, audit rows, token issue
  integrations/otp_provider.py   Fake + 2Factor providers (adapter)
  tokens.py             short-lived token after OTP (JWT)
  deps.py               require_phone_token dependency
  routers/health.py     GET /health, GET /health/db
  routers/otp.py        POST /auth/otp/send, POST /auth/otp/verify
  routers/clients.py    POST /clients, GET /clients/{id}, PATCH /clients/{id}
tests/test_validate.py   unit tests for validate.py (no DB needed)
therapy-api.postman_collection.json   import into Postman
```

## Endpoints
| Method | Path | Notes |
|---|---|---|
| POST | /auth/otp/send | `{phone}` -> 202. Same answer for any number. Rate limited |
| POST | /auth/otp/verify | `{phone, code}` -> `access_token` (15 min), `client_id`, `is_new_client` |
| POST | /clients | **Needs `Authorization: Bearer <access_token>`**; body phone must match the token. phone + source required. Accepts `referral_code` (e.g. "PARTNERX"), not a UUID |
| GET | /clients/{id} | 404 if missing |
| PATCH | /clients/{id} | Only first_name, last_name, dob, email. Send `null` to clear |

## Rules enforced
- phone: international format; spaces/dashes stripped; unique (409 on duplicate)
- email: optional, validated, stored lowercase, duplicates allowed (matches schema)
- dob: optional, after 1900-01-01, not in the future
- source: match_form | whatsapp | web
- unknown fields rejected (e.g. phone_verified_at cannot be set by callers)
- phone, source, referral_code cannot be changed via PATCH

## Setup (Windows, VS Code terminal)
1. `powershell -ExecutionPolicy Bypass -File .\setup.ps1`
2. Fill in `.env` (SUPABASE_URL without /rest/v1, SUPABASE_SECRET_KEY = sb_secret_...)
3. `.\.venv\Scripts\Activate.ps1`
4. `uvicorn app.main:app --reload`   (restart manually after editing .env)

## Phone OTP
```
POST /auth/otp/send    -> code sent (fake provider: printed in the server terminal)
POST /auth/otp/verify  -> access_token
  is_new_client=true   -> POST /clients with the token
  is_new_client=false  -> client_id returned (phone_verified_at updated)
```
- Provider is chosen by `OTP_PROVIDER` in `.env`: `fake` (tests/local) or `2factor` (real SMS, India).
  Switching needs only `.env` changes. `fake` is refused when `APP_ENV=production`.
- Limits (configurable in `.env`): 3 sends/phone/10 min, 10 sends/IP/hour, 5 wrong codes per code,
  **50 sends/24h across all users** (budget guard), Indian numbers only (`+91`).
- Codes are never stored or logged by us. `otp_verifications` is an audit + rate-limit log.
- Still open: GET/PATCH /clients are not protected yet (local only).

## Validation (app/validate.py)
Write field rules once, reuse everywhere. New schemas must import types from here:
`Phone`, `Email`, `Name`, `Dob`, `Timestamp`, `ReferralCode`, `CouponCode`, `Money`, `Url`, `TagList`, ...
plus `Optional*` variants and Literal types for every DB CHECK constraint.
All request models extend `InputModel` (rejects unknown fields).

## Tests
```
pip install -r requirements-dev.txt
pytest -v
```

## Database migrations
Schema changes go through Flyway. See `db/README.md`.

## Troubleshooting
`db_permission` / 42501 -> run in Supabase SQL Editor:
```sql
grant select, insert, update on public.clients to service_role;
grant select on public.referral_codes to service_role;
```

## Security rules
- `.env` holds the secret key; it is git-ignored. Never commit or share it.
- The secret key bypasses RLS. It lives ONLY in this backend.
- Error responses include raw DB messages (`details.db`) for debugging. Remove before deploying.
'@

Update-File "tests/test_otp.py" "9102329f71bc538813e42541863d2c076ef63985bfcfce496d5732b2ad5c0c08" @'
"""Phone OTP flow end to end, with a fake DB and the fake SMS provider."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.services.clients as clients_svc
import app.services.otp as otp_svc
from app.config import Settings
from app.integrations.otp_provider import FakeOtpProvider, OtpProviderError
from app.main import app
from tests.fakes import FakeSupabase

PHONE = "+919000000011"


@pytest.fixture
def env(monkeypatch):
    db, provider = FakeSupabase(), FakeOtpProvider()
    monkeypatch.setattr(otp_svc, "get_supabase", lambda: db)
    monkeypatch.setattr(clients_svc, "get_supabase", lambda: db)
    monkeypatch.setattr(otp_svc, "get_otp_provider", lambda: provider)
    return TestClient(app), db, provider


def send(c, phone=PHONE):
    return c.post("/auth/otp/send", json={"phone": phone})


def verify(c, code, phone=PHONE):
    return c.post("/auth/otp/verify", json={"phone": phone, "code": code})


def otp_rows(db, phone=PHONE):
    return [r for r in db.db["otp_verifications"] if r["phone"] == phone]


# ---------------- send ----------------
def test_send_records_row_without_code(env):
    c, db, p = env
    r = send(c, "+91 90000 00011")
    assert r.status_code == 202 and r.json()["expires_in"] == 600
    (row,) = otp_rows(db)
    assert row["status"] == "sent" and row["provider"] == "fake"
    assert p.last_code(PHONE) not in str(row)  # code never stored


def test_send_rejects_bad_phone_and_whatsapp(env):
    c, _, _ = env
    assert send(c, "98765").status_code == 422
    assert c.post("/auth/otp/send", json={"phone": PHONE, "channel": "whatsapp"}).status_code == 422


def test_phone_rate_limit(env):
    c, _, _ = env
    assert [send(c).status_code for _ in range(4)] == [202, 202, 202, 429]


def test_ip_rate_limit(env, monkeypatch):
    c, db, _ = env
    monkeypatch.setattr(otp_svc, "_clean_ip", lambda ip: "10.0.0.1")
    codes = [send(c, f"+9190000001{i:02d}").status_code for i in range(11)]
    assert codes[:10] == [202] * 10 and codes[10] == 429


def test_new_send_retires_old_code(env):
    c, db, p = env
    send(c); send(c)
    assert [r["status"] for r in otp_rows(db)] == ["expired", "sent"]


def test_provider_failure_is_502_and_counted(env, monkeypatch):
    c, db, p = env
    def boom(*a): raise OtpProviderError("down")
    monkeypatch.setattr(p, "send", boom)
    assert send(c).status_code == 502
    assert otp_rows(db)[0]["status"] == "failed"


# ---------------- verify ----------------
def test_verify_new_client_then_create(env):
    c, db, p = env
    send(c)
    r = verify(c, p.last_code(PHONE))
    body = r.json()
    assert r.status_code == 200 and body["verified"] and body["is_new_client"] and body["client_id"] is None
    assert otp_rows(db)[0]["status"] == "verified"

    auth = {"Authorization": f"Bearer {body['access_token']}"}
    created = c.post("/clients", json={"phone": PHONE, "source": "web"}, headers=auth)
    assert created.status_code == 201 and created.json()["phone_verified"] is True


def test_verify_existing_client_marks_verified(env):
    c, db, p = env
    db.db["clients"].append({"id": "11111111-1111-1111-1111-111111111111", "phone": PHONE,
                             "phone_verified_at": None})
    send(c)
    body = verify(c, p.last_code(PHONE)).json()
    assert body["client_id"] == "11111111-1111-1111-1111-111111111111" and not body["is_new_client"]
    assert db.db["clients"][0]["phone_verified_at"] is not None


def test_code_is_single_use(env):
    c, _, p = env
    send(c)
    code = p.last_code(PHONE)
    assert verify(c, code).status_code == 200
    assert verify(c, code).status_code == 400


def test_wrong_code_counts_and_burns_after_max(env):
    c, db, p = env
    send(c)
    good = p.last_code(PHONE)
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        assert verify(c, bad).json()["error"]["code"] == "invalid_code"
    assert otp_rows(db)[0]["status"] == "failed"
    assert verify(c, good).status_code == 400  # burned


def test_expired_code(env):
    c, db, p = env
    send(c)
    otp_rows(db)[0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert verify(c, p.last_code(PHONE)).status_code == 400
    assert otp_rows(db)[0]["status"] == "expired"


def test_verify_without_send(env):
    c, _, _ = env
    assert verify(c, "123456").status_code == 400


def test_bad_code_format(env):
    c, _, _ = env
    assert verify(c, "12ab").status_code == 422


# ---------------- token on POST /clients ----------------
def test_create_client_needs_token(env):
    c, _, _ = env
    r = c.post("/clients", json={"phone": PHONE, "source": "web"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "missing_token"
    r = c.post("/clients", json={"phone": PHONE, "source": "web"}, headers={"Authorization": "Bearer junk"})
    assert r.status_code == 401


def test_token_for_other_phone_is_403(env):
    c, _, p = env
    send(c)
    token = verify(c, p.last_code(PHONE)).json()["access_token"]
    r = c.post("/clients", json={"phone": "+919000000099", "source": "web"},
               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_tampered_token_is_401(env):
    c, _, p = env
    send(c)
    token = verify(c, p.last_code(PHONE)).json()["access_token"]
    r = c.post("/clients", json={"phone": PHONE, "source": "web"},
               headers={"Authorization": f"Bearer {token[:-2]}xx"})
    assert r.status_code == 401


# ---------------- config guards ----------------
BASE = dict(_env_file=None, supabase_url="https://x.supabase.co",
            supabase_secret_key="sb_secret_x", otp_token_secret="s" * 40)


def test_config_guards():
    with pytest.raises(ValidationError):
        Settings(**BASE, app_env="production", otp_provider="fake")
    with pytest.raises(ValidationError):
        Settings(**{**BASE, "otp_token_secret": "short"})
    with pytest.raises(ValidationError):
        Settings(**BASE, otp_provider="twilio")  # removed provider


# ---------------- country + daily budget guard ----------------
def test_non_indian_number_rejected(env):
    c, db, _ = env
    r = send(c, "+14155550100")
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_country"
    assert db.db["otp_verifications"] == []  # nothing sent, nothing paid


def test_daily_budget_cap(env, monkeypatch):
    c, _, _ = env
    capped = otp_svc.get_settings().model_copy(update={"otp_max_sends_per_day": 2})
    monkeypatch.setattr(otp_svc, "get_settings", lambda: capped)
    codes = [send(c, f"+9190000002{i:02d}").status_code for i in range(3)]
    assert codes == [202, 202, 503]


# ---------------- 2Factor adapter (HTTP mocked, nothing sent) ----------------
from app.integrations.otp_provider import TwoFactorProvider  # noqa: E402

KEY = "secret-key-123"


def twofactor(handler, template=None):
    return TwoFactorProvider(KEY, template, transport=httpx.MockTransport(handler))


def test_2factor_send_url_and_session():
    seen = {}
    def handler(req):
        seen["path"] = req.url.path
        return httpx.Response(200, json={"Status": "Success", "Details": "SESS-1"})
    assert twofactor(handler, "LOGIN_OTP").send(PHONE, "sms") == "SESS-1"
    assert seen["path"] == f"/API/V1/{KEY}/SMS/919000000011/AUTOGEN/LOGIN_OTP"  # no '+'


@pytest.mark.parametrize("details,status,expected", [
    ("OTP Matched", "Success", "approved"),
    ("OTP Mismatch", "Error", "pending"),
    ("OTP Expired", "Success", "expired"),
    ("Invalid Session", "Error", "failed"),
])
def test_2factor_check_mapping(details, status, expected):
    t = twofactor(lambda r: httpx.Response(200, json={"Status": status, "Details": details}))
    assert t.check(PHONE, "123456", "SESS-1") == expected


def test_2factor_errors_never_leak_key():
    for handler in (lambda r: httpx.Response(200, json={"Status": "Error", "Details": "Invalid API Key"}),
                    lambda r: httpx.Response(502, text="<html>bad gateway</html>")):
        with pytest.raises(OtpProviderError) as e:
            twofactor(handler).send(PHONE, "sms")
        assert KEY not in str(e.value)
    def down(req): raise httpx.ConnectError("boom", request=req)
    with pytest.raises(OtpProviderError) as e:
        twofactor(down).send(PHONE, "sms")
    assert KEY not in str(e.value)


def test_2factor_config_needs_key():
    with pytest.raises(ValidationError):
        Settings(**BASE, otp_provider="2factor")
    assert Settings(**BASE, otp_provider="2factor", twofactor_api_key="k").otp_provider == "2factor"
'@

Update-File "db/migrations/V20261125120000__otp_2factor_provider.sql" "" @'
-- Allow provider = '2factor' (2Factor.in, Indian SMS OTP provider).
-- Additive only: widens the allowed values, no data changed.

do $$
declare
  c text;
begin
  select conname into c
  from pg_constraint
  where conrelid = 'public.otp_verifications'::regclass
    and contype = 'c'
    and pg_get_constraintdef(oid) ilike '%provider%';
  if c is not null then
    execute format('alter table public.otp_verifications drop constraint %I', c);
  end if;
end $$;

alter table public.otp_verifications
  add constraint otp_verifications_provider_check
  check (provider in ('msg91', 'twilio', 'fake', '2factor'));
'@

if ($skipped.Count -gt 0) { Write-Host "`nSome files were skipped. Paste this output to Claude." -ForegroundColor Yellow }
else { Write-Host "`nAll files updated. Next: pytest -q" -ForegroundColor Green }