from sqlalchemy import Column, Integer, String, Text
from app.core.database import Base

class TemporaryDocument(Base):
    __tablename__ = "temporary_documents"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(String, unique=True, index=True, nullable=False)
    text_content = Column(Text, nullable=False)
