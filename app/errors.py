"""One place that turns every failure into a consistent JSON error.

Every error response looks like:
    {"error": {"code": "...", "message": "...", "details": ...}}
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError


class AppError(Exception):
    """Raise this from services for expected failures (not found, conflict...)."""

    def __init__(self, status: int, code: str, message: str, details=None):
        self.status, self.code, self.message, self.details = status, code, message, details


def _body(code: str, message: str, details=None) -> dict:
    err = {"code": code, "message": message}
    if details is not None:
        err["details"] = details
    return {"error": err}


# Postgres / PostgREST error codes -> (HTTP status, our code, user-facing message)
_PG_ERRORS = {
    "23505": (409, "conflict", "A record with this value already exists."),
    "23514": (422, "check_failed", "A value failed a database rule."),
    "23503": (422, "invalid_reference", "A referenced record does not exist."),
    "23502": (422, "missing_value", "A required value is missing."),
    "22P02": (400, "invalid_format", "A value has an invalid format."),
    "42501": (500, "db_permission",
              "Backend role lacks table permission. Run the GRANT for this table."),
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, e: AppError):
        return JSONResponse(status_code=e.status, content=_body(e.code, e.message, e.details))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        # Simplify Pydantic's verbose errors to field + message.
        details = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
            for err in e.errors()
        ]
        return JSONResponse(status_code=422, content=_body("validation_error", "Invalid input.", details))

    @app.exception_handler(APIError)
    async def _db_error(_: Request, e: APIError):
        status, code, message = _PG_ERRORS.get(
            e.code, (500, "database_error", "Unexpected database error.")
        )
        # Dev-only: include the raw DB message so you can debug. Remove before deploying.
        return JSONResponse(status_code=status, content=_body(code, message, {"db": e.message}))