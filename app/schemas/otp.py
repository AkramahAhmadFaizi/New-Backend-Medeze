"""Request/response shapes for phone OTP."""
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.validate import InputModel, OtpCode, Phone


class OtpSendRequest(InputModel):
    phone: Phone = Field(examples=["+919876543210"])
    channel: Literal["sms"] = "sms"  # v1: SMS only


class OtpSendResponse(BaseModel):
    message: str
    expires_in: int  # seconds the code stays valid


class OtpVerifyRequest(InputModel):
    phone: Phone = Field(examples=["+919876543210"])
    code: OtpCode = Field(examples=["123456"])


class OtpVerifyResponse(BaseModel):
    verified: bool
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    client_id: Optional[UUID]   # set when this phone already belongs to a client
    is_new_client: bool         # true -> next step is POST /clients with this token