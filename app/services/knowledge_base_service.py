from sqlalchemy.orm import Session
from app.models import knowledge_base as models_knowledge_base
from app.schemas import knowledge_base as schemas_knowledge_base

def get_knowledge_base(db: Session, knowledge_base_id: int, company_id: int):
    return db.query(models_knowledge_base.KnowledgeBase).filter(
        models_knowledge_base.KnowledgeBase.id == knowledge_base_id,
        models_knowledge_base.KnowledgeBase.company_id == company_id
    ).first()

def get_knowledge_bases(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_knowledge_base.KnowledgeBase).filter(
        models_knowledge_base.KnowledgeBase.company_id == company_id
    ).offset(skip).limit(limit).all()

def create_knowledge_base(db: Session, knowledge_base: schemas_knowledge_base.KnowledgeBaseCreate, company_id: int):
    db_knowledge_base = models_knowledge_base.KnowledgeBase(**knowledge_base.dict(), company_id=company_id)
    db.add(db_knowledge_base)
    db.commit()
    db.refresh(db_knowledge_base)
    return db_knowledge_base

def update_knowledge_base(db: Session, knowledge_base_id: int, knowledge_base: schemas_knowledge_base.KnowledgeBaseUpdate, company_id: int):
    db_knowledge_base = get_knowledge_base(db, knowledge_base_id, company_id)
    if db_knowledge_base:
        for key, value in knowledge_base.dict(exclude_unset=True).items():
            setattr(db_knowledge_base, key, value)
        db.commit()
        db.refresh(db_knowledge_base)
    return db_knowledge_base

def delete_knowledge_base(db: Session, knowledge_base_id: int, company_id: int):
    db_knowledge_base = get_knowledge_base(db, knowledge_base_id, company_id)
    if db_knowledge_base:
        db.delete(db_knowledge_base)
        db.commit()
    return db_knowledge_base
