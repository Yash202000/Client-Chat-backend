from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.core.auth import get_current_active_user
from app.models.user import User
from app.schemas.processing_template import ProcessingTemplate, ProcessingTemplateCreate, ProcessingTemplateUpdate
from app.crud import crud_processing_template

router = APIRouter()

@router.post("/", response_model=ProcessingTemplate)
def create_processing_template(
    *,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    template_in: ProcessingTemplateCreate
):
    """
    Create new processing template.
    """
    template = crud_processing_template.create_processing_template(db=db, obj_in=template_in, company_id=current_user.company_id)
    return template

@router.get("/", response_model=List[ProcessingTemplate])
def read_processing_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    skip: int = 0,
    limit: int = 100,
):
    """
    Retrieve processing templates.
    """
    templates = crud_processing_template.get_multi_processing_templates(db=db, company_id=current_user.company_id, skip=skip, limit=limit)
    return templates

@router.get("/{id}", response_model=ProcessingTemplate)
def read_processing_template(
    *,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    id: int,
):
    """
    Get processing template by ID.
    """
    template = crud_processing_template.get_processing_template(db=db, id=id, company_id=current_user.company_id)
    if not template:
        raise HTTPException(status_code=404, detail="Processing template not found")
    return template

@router.put("/{id}", response_model=ProcessingTemplate)
def update_processing_template(
    *,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    id: int,
    template_in: ProcessingTemplateUpdate,
):
    """
    Update a processing template.
    """
    template = crud_processing_template.get_processing_template(db=db, id=id, company_id=current_user.company_id)
    if not template:
        raise HTTPException(status_code=404, detail="Processing template not found")
    template = crud_processing_template.update_processing_template(db=db, db_obj=template, obj_in=template_in)
    return template

@router.delete("/{id}", response_model=ProcessingTemplate)
def delete_processing_template(
    *,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    id: int,
):
    """
    Delete a processing template.
    """
    template = crud_processing_template.get_processing_template(db=db, id=id, company_id=current_user.company_id)
    if not template:
        raise HTTPException(status_code=404, detail="Processing template not found")
    template = crud_processing_template.delete_processing_template(db=db, db_obj=template)
    return template
