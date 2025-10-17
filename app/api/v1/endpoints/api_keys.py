from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.dependencies import get_db, get_current_user
from app.schemas.api_key import ApiKey, ApiKeyCreate
from app.services import api_key_service
from app.models import user as models

router = APIRouter()

@router.get("/", response_model=List[ApiKey])
def read_api_keys(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return api_key_service.get_api_keys_by_company(db, current_user.company_id)

@router.post("/", response_model=ApiKey, status_code=status.HTTP_201_CREATED)
def create_api_key(
    api_key: ApiKeyCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return api_key_service.create_api_key(db, api_key, current_user.company_id)

@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(
    api_key_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    api_key = api_key_service.get_api_key_by_id(db, api_key_id)
    if not api_key or api_key.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="API Key not found")
    api_key_service.delete_api_key(db, api_key_id, current_user.company_id)
    return
