"""Short-lived token issued after a successful phone OTP.

It proves "this caller verified this phone in the last 15 minutes".
Later this grows into a real login session (refresh tokens etc).
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from pydantic import BaseModel

from app.config import get_settings
from app.errors import AppError

ALGORITHM = "HS256"
TOKEN_TYPE = "phone_verified"


class PhoneClaims(BaseModel):
    phone: str
    client_id: Optional[str]


def issue_phone_token(phone: str, client_id: Optional[str]) -> tuple[str, int]:
    s = get_settings()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": phone,
        "cid": client_id,
        "typ": TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(seconds=s.otp_token_ttl_seconds),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(claims, s.otp_token_secret.get_secret_value(), algorithm=ALGORITHM)
    return token, s.otp_token_ttl_seconds


def decode_phone_token(token: str) -> PhoneClaims:
    s = get_settings()
    try:
        claims = jwt.decode(
            token,
            s.otp_token_secret.get_secret_value(),
            algorithms=[ALGORITHM],  # never accept the algorithm the token claims
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError:
        raise AppError(401, "token_expired", "Verification expired. Request a new code.")
    except jwt.InvalidTokenError:
        raise AppError(401, "invalid_token", "Invalid token.")
    if claims.get("typ") != TOKEN_TYPE:
        raise AppError(401, "invalid_token", "Invalid token.")
    return PhoneClaims(phone=claims["sub"], client_id=claims.get("cid"))