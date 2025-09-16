from sqlalchemy.orm import Session
from app.models.temporary_document import TemporaryDocument
import uuid

def create_temporary_document(db: Session, *, text_content: str) -> TemporaryDocument:
    document_id = str(uuid.uuid4())
    db_obj = TemporaryDocument(
        document_id=document_id,
        text_content=text_content
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def get_temporary_document(db: Session, *, document_id: str) -> TemporaryDocument:
    return db.query(TemporaryDocument).filter(TemporaryDocument.document_id == document_id).first()
