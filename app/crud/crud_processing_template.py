from sqlalchemy.orm import Session
from app.models.processing_template import ProcessingTemplate
from app.schemas.processing_template import ProcessingTemplateCreate, ProcessingTemplateUpdate

def create_processing_template(db: Session, *, obj_in: ProcessingTemplateCreate, company_id: int) -> ProcessingTemplate:
    db_obj = ProcessingTemplate(
        **obj_in.dict(),
        company_id=company_id
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def get_processing_template(db: Session, id: int, company_id: int) -> ProcessingTemplate:
    return db.query(ProcessingTemplate).filter(ProcessingTemplate.id == id, ProcessingTemplate.company_id == company_id).first()

def get_multi_processing_templates(db: Session, *, company_id: int, skip: int = 0, limit: int = 100) -> list[ProcessingTemplate]:
    return db.query(ProcessingTemplate).filter(ProcessingTemplate.company_id == company_id).offset(skip).limit(limit).all()

def update_processing_template(db: Session, *, db_obj: ProcessingTemplate, obj_in: ProcessingTemplateUpdate) -> ProcessingTemplate:
    update_data = obj_in.model_dump(exclude_unset=True)
    for field in update_data:
        setattr(db_obj, field, update_data[field])
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def delete_processing_template(db: Session, *, db_obj: ProcessingTemplate) -> ProcessingTemplate:
    db.delete(db_obj)
    db.commit()
    return db_obj
