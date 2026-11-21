"""ONE shared Medisina HTTP client for the whole app (like db.py in the main backend).

What it does for you on every call:
  - builds the URL from MEDISINA_API_BASE_URL (never from the contract)
  - adds Authorization: Bearer <token>
  - logs in (POST /auth/login) the first time a token is needed
  - refreshes (POST /auth/refresh) shortly before the token expires,
    and once more if Medisina still answers 401
  - logs in again from scratch if the refresh token is rejected
  - unwraps Medisina's {"success", "data", "error"} envelope and returns `data`,
    or raises MedisinaError

Usage in a service:
    from app.medisina.client import get_medisina
    from app.medisina import operations as ops

    data = get_medisina().call(ops.GET_DOCTOR, path_params={"id": 42})
"""
import threading
import time
from functools import lru_cache
from typing import Any, Optional

import httpx

from app.config import get_settings
from app.medisina import operations as ops

# Refresh this many seconds before the token's stated expiry, so a request
# never leaves with a token that dies on the way.
EXPIRY_SKEW_SECONDS = 30
# Used if Medisina ever omits expiresIn. The 401 retry still covers us.
DEFAULT_EXPIRES_IN = 300


class MedisinaError(Exception):
    """A Medisina call failed. upstream_status is Medisina's HTTP status
    (or 502/504 for network problems); code/message come from its error envelope."""

    def __init__(self, upstream_status: int, code: str, message: str):
        super().__init__(f"{upstream_status} {code}: {message}")
        self.upstream_status, self.code, self.message = upstream_status, code, message


class MedisinaAuthError(MedisinaError):
    """Our own login to Medisina failed (wrong credentials in .env, account locked...)."""


class MedisinaNetworkError(MedisinaError):
    """Medisina could not be reached or did not answer in time (no HTTP response)."""


class MedisinaClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        user_type: str,
        timeout: float = 15.0,
        transport: Optional[httpx.BaseTransport] = None,  # tests inject a fake here
    ):
        self._creds = {"email": email, "password": password, "userType": user_type}
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )
        # FastAPI runs sync routes in a thread pool, so many requests may need
        # a token at the same moment. The lock makes sure only one logs in/refreshes.
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._expires_at = 0.0  # time.monotonic() deadline

    # ------------------------------------------------------------------ public
    def call(
        self,
        op: ops.Op,
        *,
        path_params: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        json: Any = None,
    ) -> Any:
        """Call a Medisina endpoint and return the `data` part of its response."""
        path = op.path.format(**(path_params or {}))
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        if not op.auth:
            return self._unwrap(self._send(op.method, path, params, json, token=None))

        token = self._current_token()
        resp = self._send(op.method, path, params, json, token)
        if resp.status_code == 401:
            # Token was revoked or expired early: renew once and retry once.
            token = self._renew(stale_token=token)
            resp = self._send(op.method, path, params, json, token)
        return self._unwrap(resp)

    def ensure_logged_in(self) -> None:
        """Get a valid token now (used by GET /health/medisina)."""
        self._current_token()

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ tokens
    def _current_token(self) -> str:
        with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            return self._renew_locked()

    def _renew(self, stale_token: str) -> str:
        with self._lock:
            if self._token and self._token != stale_token:
                return self._token  # another thread already renewed it
            return self._renew_locked()

    def _renew_locked(self) -> str:
        """Refresh if we can, otherwise (or if refresh fails) log in again."""
        if self._refresh_token:
            try:
                data = self._unwrap(
                    self._send(ops.REFRESH.method, ops.REFRESH.path, None,
                               {"refreshToken": self._refresh_token}, token=None)
                )
                self._store(data["token"], data.get("expiresIn"))
                return self._token
            except MedisinaNetworkError:
                raise  # Medisina is down/slow: keep the refresh token for next time
            except (MedisinaError, KeyError, TypeError):
                self._refresh_token = None  # dead; fall through to a full login

        try:
            data = self._unwrap(
                self._send(ops.LOGIN.method, ops.LOGIN.path, None, self._creds, token=None)
            )
            self._store(data["token"], data.get("expiresIn"))
            self._refresh_token = data.get("refreshToken")
        except MedisinaNetworkError:
            raise  # Medisina is down/slow: not a credentials problem
        except MedisinaError as e:
            raise MedisinaAuthError(e.upstream_status, e.code, e.message) from e
        except (KeyError, TypeError) as e:
            raise MedisinaAuthError(502, "BAD_LOGIN_RESPONSE",
                                    "Login response had no token.") from e
        return self._token

    def _store(self, token: str, expires_in: Any) -> None:
        try:
            seconds = float(expires_in)
        except (TypeError, ValueError):
            seconds = DEFAULT_EXPIRES_IN
        self._token = token
        self._expires_at = time.monotonic() + max(seconds - EXPIRY_SKEW_SECONDS, 0)

    # ------------------------------------------------------------------ HTTP
    def _send(self, method, path, params, json, token: Optional[str]) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        try:
            return self._http.request(method, path, params=params, json=json, headers=headers)
        except httpx.TimeoutException as e:
            raise MedisinaNetworkError(504, "TIMEOUT", f"Medisina did not answer in time ({e}).") from e
        except httpx.HTTPError as e:
            raise MedisinaNetworkError(502, "UNREACHABLE", f"{type(e).__name__}: {e}") from e

    @staticmethod
    def _unwrap(resp: httpx.Response) -> Any:
        try:
            body = resp.json()
        except ValueError:
            raise MedisinaError(
                resp.status_code if resp.is_error else 502,
                "NON_JSON_RESPONSE",
                f"Medisina returned non-JSON (HTTP {resp.status_code}).",
            )
        if not isinstance(body, dict):
            raise MedisinaError(502, "BAD_RESPONSE", "Medisina response was not a JSON object.")

        if resp.is_success and body.get("success") is True:
            return body.get("data")

        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        status = resp.status_code if resp.is_error else 502  # 200 + success:false
        raise MedisinaError(
            status,
            str(err.get("code") or "UNKNOWN"),
            str(err.get("message") or body.get("message") or "Medisina request failed."),
        )


@lru_cache
def get_medisina() -> MedisinaClient:
    s = get_settings()
    return MedisinaClient(
        base_url=s.medisina_api_base_url,
        email=s.medisina_email,
        password=s.medisina_password.get_secret_value(),
        user_type=s.medisina_user_type,
        timeout=s.medisina_timeout_seconds,
    )


def close_medisina() -> None:
    if get_medisina.cache_info().currsize:
        get_medisina().close()
        get_medisina.cache_clear()
