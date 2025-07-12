from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, HttpUrl

from app.schemas import knowledge_base as schemas_knowledge_base
from app.services import knowledge_base_service
from app.core.dependencies import get_db, get_current_company

router = APIRouter()

class KnowledgeBaseCreateFromURL(BaseModel):
    url: HttpUrl
    name: str
    description: str | None = None
    knowledge_base_id: Optional[int] = None # New field for appending

@router.post("/from-url", response_model=schemas_knowledge_base.KnowledgeBase)
def create_knowledge_base_from_url(
    kb_from_url: KnowledgeBaseCreateFromURL,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company)
):
    try:
        content = knowledge_base_service.extract_text_from_url(str(kb_from_url.url))
        
        if kb_from_url.knowledge_base_id:
            # Append to existing knowledge base
            existing_kb = knowledge_base_service.get_knowledge_base(db, kb_from_url.knowledge_base_id, current_company_id)
            if not existing_kb:
                raise HTTPException(status_code=404, detail="Existing Knowledge Base not found")
            
            updated_content = existing_kb.content + "\n\n" + content # Append new content
            updated_kb = schemas_knowledge_base.KnowledgeBaseUpdate(
                name=existing_kb.name, # Keep existing name
                description=existing_kb.description, # Keep existing description
                content=updated_content
            )
            return knowledge_base_service.update_knowledge_base(db, existing_kb.id, updated_kb, current_company_id)
        else:
            # Create new knowledge base
            knowledge_base = schemas_knowledge_base.KnowledgeBaseCreate(
                name=kb_from_url.name,
                description=kb_from_url.description,
                content=content
            )
            return knowledge_base_service.create_knowledge_base(db, knowledge_base, current_company_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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

@router.post("/{knowledge_base_id}/generate-qna", response_model=schemas_knowledge_base.KnowledgeBaseQnA)
async def generate_qna_for_knowledge_base(
    knowledge_base_id: int,
    qna_generate: schemas_knowledge_base.KnowledgeBaseQnAGenerate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company)
):
    try:
        generated_content = await knowledge_base_service.generate_qna_from_knowledge_base(db, knowledge_base_id, current_company_id, qna_generate.prompt)
        
        # Update the knowledge base with the generated Q&A
        updated_kb_schema = schemas_knowledge_base.KnowledgeBaseUpdate(content=generated_content)
        updated_kb = knowledge_base_service.update_knowledge_base(db, knowledge_base_id, updated_kb_schema, current_company_id)
        
        if not updated_kb:
            raise HTTPException(status_code=404, detail="Knowledge Base not found after Q&A generation")

        return schemas_knowledge_base.KnowledgeBaseQnA(generated_content=generated_content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate Q&A: {e}")
