from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db, get_current_active_user, get_current_company
from app.models import user as models_user
from app.schemas import integration as schemas_integration
from app.services import integration_service

router = APIRouter()

@router.post("/", response_model=schemas_integration.Integration)
def create_integration(
    integration: schemas_integration.IntegrationCreate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Create a new integration for the current user's company.
    """
    # TODO: Add permission check to ensure user is a company admin
    return integration_service.create_integration(db=db, integration=integration, company_id=current_company_id)

@router.get("/", response_model=List[schemas_integration.Integration])
def read_integrations(
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Retrieve all integrations for the current user's company.
    """
    return integration_service.get_integrations_by_company(db, company_id=current_company_id)

@router.get("/{integration_id}", response_model=schemas_integration.Integration)
def read_integration(
    integration_id: int,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Retrieve a specific integration by ID.
    """
    db_integration = integration_service.get_integration(db, integration_id=integration_id, company_id=current_company_id)
    if db_integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    return db_integration

@router.put("/{integration_id}", response_model=schemas_integration.Integration)
def update_integration(
    integration_id: int,
    integration_in: schemas_integration.IntegrationUpdate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update an integration.
    """
    db_integration = integration_service.get_integration(db, integration_id=integration_id, company_id=current_company_id)
    if db_integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    # TODO: Add permission check
    return integration_service.update_integration(db=db, db_integration=db_integration, integration_in=integration_in)

@router.delete("/{integration_id}", response_model=schemas_integration.Integration)
def delete_integration(
    integration_id: int,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Delete an integration.
    """
    db_integration = integration_service.delete_integration(db, integration_id=integration_id, company_id=current_company_id)
    if db_integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    # TODO: Add permission check
    return db_integration
