"""HTTP layer for phone OTP."""
from fastapi import APIRouter, Request, status

from app.schemas.otp import OtpSendRequest, OtpSendResponse, OtpVerifyRequest, OtpVerifyResponse
from app.services import otp as service

router = APIRouter(prefix="/auth/otp", tags=["auth"])


@router.post("/send", response_model=OtpSendResponse, status_code=status.HTTP_202_ACCEPTED)
def send_otp(body: OtpSendRequest, request: Request):
    ip = request.client.host if request.client else None
    return service.send_otp(body.phone, body.channel, ip)


@router.post("/verify", response_model=OtpVerifyResponse)
def verify_otp(body: OtpVerifyRequest):
    return service.verify_otp(body.phone, body.code)