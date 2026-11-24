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