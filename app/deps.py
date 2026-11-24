"""Reusable FastAPI dependencies."""
from typing import Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import AppError
from app.tokens import PhoneClaims, decode_phone_token

_bearer = HTTPBearer(auto_error=False)  # adds the "Authorize" button in /docs


def require_phone_token(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> PhoneClaims:
    """Endpoint needs 'Authorization: Bearer <token from /auth/otp/verify>'."""
    if creds is None:
        raise AppError(401, "missing_token", "Verify your phone first (POST /auth/otp/verify).")
    return decode_phone_token(creds.credentials)