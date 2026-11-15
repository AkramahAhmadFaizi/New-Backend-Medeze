"""Health checks: is the server up, and can it reach the database?"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError

from app.db import get_supabase

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health():
    """Server is running. Does not touch the database."""
    return {"status": "ok"}


@router.get("/db")
def health_db():
    """Runs a tiny read on the clients table to prove the connection works."""
    try:
        get_supabase().table("clients").select("id").limit(1).execute()
        return {"database": "ok"}
    except APIError as e:
        # Dev-only detail so you can diagnose. Remove details before deploying.
        return JSONResponse(
            status_code=503,
            content={"database": "error", "code": e.code, "message": e.message},
        )
    except Exception as e:  # network errors, bad URL, etc.
        return JSONResponse(
            status_code=503,
            content={"database": "error", "message": f"{type(e).__name__}: {e}"},
        )
