"""Loads settings from the .env file and validates them at startup."""
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str
    supabase_secret_key: SecretStr  # SecretStr hides the value in logs/prints

    # ---- Medisina API (contract reference: portal-backend/) ----
    # The contract has no servers list, so the base URL comes ONLY from here.
    medisina_api_base_url: str
    medisina_email: str
    medisina_password: SecretStr
    medisina_user_type: Literal["PATIENT", "DOCTOR"]
    medisina_timeout_seconds: float = 15.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("supabase_url")
    @classmethod
    def check_url(cls, v: str) -> str:
        v = v.rstrip("/")
        if not v.startswith("https://") or "/rest/v1" in v:
            raise ValueError(
                "SUPABASE_URL must be the project URL, e.g. "
                "https://abcd.supabase.co (without /rest/v1)"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
