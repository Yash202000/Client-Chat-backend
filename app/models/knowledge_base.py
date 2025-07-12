from sqlalchemy import Column, Integer, String, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    content = Column(Text) # Storing content directly for simplicity, can be a reference to a file/storage
    embeddings = Column(JSON, nullable=True) # Storing vector embeddings
    company_id = Column(Integer, ForeignKey("companies.id"))

    company = relationship("Company", back_populates="knowledge_bases")
