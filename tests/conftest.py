"""Test settings: never touch a real database or SMS provider."""
import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "sb_secret_test")
os.environ["OTP_TOKEN_SECRET"] = "test-secret-" + "x" * 40
os.environ["OTP_PROVIDER"] = "fake"
os.environ["APP_ENV"] = "local"