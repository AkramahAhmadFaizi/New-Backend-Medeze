"""HTTP layer for clients: URLs, status codes, request/response models. No DB code here."""
from uuid import UUID

from fastapi import APIRouter, status

from app.schemas.clients import ClientCreate, ClientOut, ClientUpdate
from app.services import clients as service

router = APIRouter(prefix="/clients", tags=["clients"])


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def create_client(body: ClientCreate):
    return service.create_client(body)


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: UUID):
    return service.get_client(client_id)


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(client_id: UUID, body: ClientUpdate):
    return service.update_client(client_id, body)