"""Business logic for clients. Routers call these; these call Supabase."""
from datetime import datetime, timezone
from uuid import UUID

from app.db import get_supabase
from app.errors import AppError
from app.schemas.clients import CLIENT_COLUMNS, ClientCreate, ClientOut, ClientUpdate


def _resolve_referral_code(code: str) -> str:
    """Turn a public code like 'PARTNERX' into its internal UUID."""
    res = (
        get_supabase().table("referral_codes")
        .select("id,is_active").eq("code", code).limit(1).execute()
    )
    if not res.data:
        raise AppError(422, "invalid_referral_code", f"Referral code '{code}' does not exist.")
    if not res.data[0]["is_active"]:
        raise AppError(422, "inactive_referral_code", f"Referral code '{code}' is no longer active.")
    return res.data[0]["id"]


def create_client(data: ClientCreate, verified_phone: str) -> ClientOut:
    # The phone in the body must be the phone the caller just verified by OTP
    if data.phone != verified_phone:
        raise AppError(403, "phone_mismatch", "Phone does not match the verified phone.")

    row = data.model_dump(mode="json", exclude={"referral_code"})
    row["phone_verified_at"] = datetime.now(timezone.utc).isoformat()  # set by server only
    if data.referral_code:
        row["referred_by_code_id"] = _resolve_referral_code(data.referral_code)

    sb = get_supabase()
    # Friendly pre-check. The UNIQUE constraint is still the real guarantee
    # (two simultaneous requests can both pass this check; the DB stops the 2nd).
    exists = sb.table("clients").select("id").eq("phone", data.phone).limit(1).execute()
    if exists.data:
        raise AppError(409, "phone_taken", "A client with this phone number already exists.")

    res = sb.table("clients").insert(row).execute()
    created_id = res.data[0]["id"]
    return get_client(created_id)


def get_client(client_id: UUID | str) -> ClientOut:
    res = (
        get_supabase().table("clients")
        .select(CLIENT_COLUMNS).eq("id", str(client_id)).limit(1).execute()
    )
    if not res.data:
        raise AppError(404, "not_found", "Client not found.")
    return ClientOut.model_validate(res.data[0])


def update_client(client_id: UUID, data: ClientUpdate) -> ClientOut:
    # exclude_unset: only fields the caller actually sent (explicit null included)
    changes = data.model_dump(mode="json", exclude_unset=True)
    if not changes:
        raise AppError(400, "empty_update", "Send at least one field to update.")

    res = (
        get_supabase().table("clients")
        .update(changes).eq("id", str(client_id)).execute()
    )
    if not res.data:
        raise AppError(404, "not_found", "Client not found.")
    return get_client(client_id)