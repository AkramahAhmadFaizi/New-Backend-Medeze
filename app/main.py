"""App entry point. Run with:  uvicorn app.main:app --reload"""
from fastapi import FastAPI

from app.config import get_settings
from app.errors import register_error_handlers
from app.routers import clients, health, otp

get_settings()  # fail fast at startup if .env is missing or wrong

app = FastAPI(title="Therapy Platform API", version="0.3.0")
register_error_handlers(app)
app.include_router(health.router)
app.include_router(otp.router)
app.include_router(clients.router)