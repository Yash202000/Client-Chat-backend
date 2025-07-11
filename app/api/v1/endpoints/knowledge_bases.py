from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.schemas import knowledge_base as schemas_knowledge_base
from app.services import knowledge_base_service
from app.core.dependencies import get_db, get_current_company

router = APIRouter()

@router.post("/", response_model=schemas_knowledge_base.KnowledgeBase)
def create_knowledge_base(
    knowledge_base: schemas_knowledge_base.KnowledgeBaseCreate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company)
):
    return knowledge_base_service.create_knowledge_base(db, knowledge_base, current_company_id)

@router.get("/{knowledge_base_id}", response_model=schemas_knowledge_base.KnowledgeBase)
def get_knowledge_base(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company)
):
    db_knowledge_base = knowledge_base_service.get_knowledge_base(db, knowledge_base_id, current_company_id)
    if db_knowledge_base is None:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    return db_knowledge_base

@router.get("/", response_model=List[schemas_knowledge_base.KnowledgeBase])
def get_knowledge_bases(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company)
):
    return knowledge_base_service.get_knowledge_bases(db, current_company_id, skip=skip, limit=limit)

@router.put("/{knowledge_base_id}", response_model=schemas_knowledge_base.KnowledgeBase)
def update_knowledge_base(
    knowledge_base_id: int,
    knowledge_base: schemas_knowledge_base.KnowledgeBaseUpdate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company)
):
    db_knowledge_base = knowledge_base_service.update_knowledge_base(db, knowledge_base_id, knowledge_base, current_company_id)
    if db_knowledge_base is None:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    return db_knowledge_base

@router.delete("/{knowledge_base_id}")
def delete_knowledge_base(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company)
):
    db_knowledge_base = knowledge_base_service.delete_knowledge_base(db, knowledge_base_id, current_company_id)
    if db_knowledge_base is None:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    return {"message": "Knowledge Base deleted successfully"}
