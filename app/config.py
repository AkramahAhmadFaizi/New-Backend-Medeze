"""Loads settings from the .env file and validates them at startup."""
from functools import lru_cache
from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Plain http is accepted only for these hosts (local Supabase / docker compose dev env).
LOCAL_HOSTS = {"localhost", "127.0.0.1", "host.docker.internal"}


class Settings(BaseSettings):
    # ---- Supabase ----
    supabase_url: str
    supabase_secret_key: SecretStr  # SecretStr hides the value in logs/prints

    # ---- Medisina API (contract reference: portal-backend/) ----
    # The contract has no servers list, so the base URL comes ONLY from here.
    medisina_api_base_url: str
    medisina_email: str
    medisina_password: SecretStr
    medisina_user_type: Literal["PATIENT", "DOCTOR"]
    medisina_timeout_seconds: float = 15.0

    # ---- App ----
    app_env: Literal["local", "staging", "production"] = "local"

    # ---- OTP provider: switch with OTP_PROVIDER in .env, no code change ----
    otp_provider: Literal["fake", "2factor"] = "fake"
    twofactor_api_key: Optional[SecretStr] = None
    twofactor_template_name: Optional[str] = None   # DLT template name in the 2Factor dashboard

    # ---- OTP rules ----
    otp_ttl_seconds: int = 600                # code valid for 10 min
    otp_max_sends_per_phone: int = 3          # per phone ...
    otp_phone_window_minutes: int = 10        # ... in this many minutes
    otp_max_sends_per_ip_per_hour: int = 10
    otp_max_attempts: int = 5                 # wrong codes before the OTP is burned
    otp_max_sends_per_day: int = 50           # GLOBAL budget guard (all phones, rolling 24h)
    otp_allowed_country_codes: str = "+91"    # comma-separated, e.g. "+91" or "+91,+971"

    # ---- Token issued after a successful OTP ----
    otp_token_secret: SecretStr
    otp_token_ttl_seconds: int = 900          # 15 min

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("supabase_url")
    @classmethod
    def check_url(cls, v: str) -> str:
        v = v.rstrip("/")
        # http:// is allowed only for the local Supabase stack (supabase start).
        # Compare the parsed hostname, not a prefix: "http://localhost.evil.com" must fail.
        u = urlparse(v)
        local = u.scheme == "http" and u.hostname in LOCAL_HOSTS
        if not (u.scheme == "https" or local) or "/rest/v1" in v:
            raise ValueError(
                "SUPABASE_URL must be the project URL, e.g. https://abcd.supabase.co "
                "(without /rest/v1). Plain http is allowed only for local Supabase."
            )
        return v

    @field_validator("medisina_api_base_url")
    @classmethod
    def check_medisina_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("https://", "http://")):
            raise ValueError(
                "MEDISINA_API_BASE_URL must be a full URL, e.g. https://api.example.com"
            )
        return v

    @field_validator("supabase_secret_key")
    @classmethod
    def check_key(cls, v: SecretStr) -> SecretStr:
        if v.get_secret_value().startswith("sb_publishable_"):
            raise ValueError(
                "That is the PUBLISHABLE key. The backend needs the SECRET key "
                "(sb_secret_...) from Project Settings -> API Keys."
            )
        return v

    @field_validator("otp_token_secret")
    @classmethod
    def check_token_secret(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError(
                "OTP_TOKEN_SECRET must be at least 32 characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return v

    @property
    def otp_country_codes(self) -> list[str]:
        return [c.strip() for c in self.otp_allowed_country_codes.split(",") if c.strip()]

    @model_validator(mode="after")
    def check_otp_provider(self):
        if self.otp_provider == "2factor" and not self.twofactor_api_key:
            raise ValueError("OTP_PROVIDER=2factor needs: TWOFACTOR_API_KEY")
        if self.app_env == "production" and self.supabase_url.startswith("http://"):
            raise ValueError("APP_ENV=production needs an https SUPABASE_URL")
        if self.app_env == "production" and self.otp_provider == "fake":
            raise ValueError("OTP_PROVIDER=fake is not allowed when APP_ENV=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()