from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db
from app.schemas import credential as schemas_credential
from app.services import credential_service
from app.core.auth import get_current_user
from app.models.user import User

router = APIRouter()

@router.post("/", response_model=schemas_credential.Credential, status_code=status.HTTP_201_CREATED)
def create_credential(
    credential: schemas_credential.CredentialCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db_credential = credential_service.get_credential_by_provider_name(
        db, provider_name=credential.provider_name, company_id=current_user.company_id
    )
    if db_credential:
        raise HTTPException(status_code=400, detail="Credential for this provider already exists")
    return credential_service.create_credential(db=db, credential=credential, company_id=current_user.company_id)

@router.get("/", response_model=List[schemas_credential.Credential])
def read_credentials(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    credentials = credential_service.get_credentials(db, company_id=current_user.company_id, skip=skip, limit=limit)
    return credentials

@router.get("/{credential_id}", response_model=schemas_credential.Credential)
def read_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db_credential = credential_service.get_credential(db, credential_id=credential_id, company_id=current_user.company_id)
    if db_credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return db_credential

@router.put("/{credential_id}", response_model=schemas_credential.Credential)
def update_credential(
    credential_id: int,
    credential: schemas_credential.CredentialUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db_credential = credential_service.update_credential(db, credential_id=credential_id, credential=credential, company_id=current_user.company_id)
    if db_credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return db_credential

@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db_credential = credential_service.delete_credential(db, credential_id=credential_id, company_id=current_user.company_id)
    if db_credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return None