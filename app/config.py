"""Loads settings from the .env file and validates them at startup."""
from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str
    supabase_secret_key: SecretStr  # SecretStr hides the value in logs/prints

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("supabase_url")
    @classmethod
    def check_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        # http is allowed only for the local Docker stack (supabase start).
        local = v.startswith(("http://127.0.0.1", "http://localhost"))
        if not (v.startswith("https://") or local) or "/rest/v1" in v:
            raise ValueError(
                "SUPABASE_URL must be the project URL, e.g. "
                "https://abcd.supabase.co or http://127.0.0.1:54321 (without /rest/v1)"
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
