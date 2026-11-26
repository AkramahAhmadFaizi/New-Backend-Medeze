"""SUPABASE_URL rules: https everywhere, plain http only for local Supabase."""
import pytest
from pydantic import ValidationError

from app.config import Settings

BASE = dict(
    _env_file=None,
    supabase_secret_key="sb_secret_x",
    otp_token_secret="s" * 40,
    medisina_api_base_url="https://medisina.example.com",
    medisina_email="svc@example.com",
    medisina_password="x",
    medisina_user_type="PATIENT",
)


@pytest.mark.parametrize("url", ["https://abcd.supabase.co", "http://127.0.0.1:54321",
                                 "http://localhost:54321", "http://host.docker.internal:54321/"])
def test_allowed_urls(url):
    assert Settings(**BASE, supabase_url=url).supabase_url == url.rstrip("/")


@pytest.mark.parametrize("url", ["http://abcd.supabase.co", "https://abcd.supabase.co/rest/v1",
                                 "http://localhost.evil.com", "http://127.0.0.1.evil.com:54321",
                                 "ftp://x", "abcd.supabase.co"])
def test_rejected_urls(url):
    with pytest.raises(ValidationError):
        Settings(**BASE, supabase_url=url)


def test_production_needs_https():
    with pytest.raises(ValidationError):
        Settings(**BASE, supabase_url="http://localhost:54321", app_env="production",
                 otp_provider="2factor", twofactor_api_key="k")
