"""Test settings: never touch a real database or SMS provider."""
import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "sb_secret_test")
os.environ.setdefault("MEDISINA_API_BASE_URL", "https://medisina.test")
os.environ.setdefault("MEDISINA_EMAIL", "svc@example.com")
os.environ.setdefault("MEDISINA_PASSWORD", "test")
os.environ.setdefault("MEDISINA_USER_TYPE", "PATIENT")
os.environ["OTP_TOKEN_SECRET"] = "test-secret-" + "x" * 40
os.environ["OTP_PROVIDER"] = "fake"
os.environ["APP_ENV"] = "local"