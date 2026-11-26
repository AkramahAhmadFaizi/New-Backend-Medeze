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