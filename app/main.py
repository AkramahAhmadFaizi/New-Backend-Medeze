"""App entry point. Run with:  uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.errors import register_error_handlers
from app.medisina.client import close_medisina
from app.routers import bookings, clients, doctors, health, specialties

get_settings()  # fail fast at startup if .env is missing or wrong


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    close_medisina()


app = FastAPI(title="Therapy Platform API", version="0.2.0", lifespan=lifespan)
register_error_handlers(app)
app.include_router(health.router)
app.include_router(clients.router)
app.include_router(doctors.router)
app.include_router(specialties.router)
app.include_router(bookings.router)
