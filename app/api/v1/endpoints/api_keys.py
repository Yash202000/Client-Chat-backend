from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.dependencies import get_db, get_current_company
from app.schemas.api_key import ApiKey, ApiKeyCreate
from app.services import api_key_service

router = APIRouter()

@router.get("/", response_model=List[ApiKey])
def read_api_keys(
    db: Session = Depends(get_db),
    company_id: int = Depends(get_current_company),
):
    return api_key_service.get_api_keys_by_company(db, company_id)

@router.post("/", response_model=ApiKey, status_code=status.HTTP_201_CREATED)
def create_api_key(
    api_key: ApiKeyCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_current_company),
):
    return api_key_service.create_api_key(db, api_key, company_id)

@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(
    api_key_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_current_company),
):
    # You might want to add a check here to ensure the api key belongs to the company
    api_key_service.delete_api_key(db, api_key_id)
    return
