from sqlalchemy import Column, Integer, String, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.agent import agent_knowledge_bases

class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"))

    # For remote knowledge bases
    type = Column(String, default="local") # 'local' or 'remote'
    provider = Column(String, nullable=True) # e.g., 'chroma', 'pinecone'
    connection_details = Column(JSON, nullable=True) # e.g., {"host": "...", "port": "...", "collection_name": "..."}

    # New fields for local, S3-backed knowledge bases
    storage_type = Column(String, nullable=True) # e.g., 's3'
    storage_details = Column(JSON, nullable=True) # e.g., {"bucket": "my-bucket", "key": "my-file.txt"}
    chroma_collection_name = Column(String, nullable=True, unique=True)
    faiss_index_id = Column(String, nullable=True) # Unique ID for the FAISS index directory

    company = relationship("Company", back_populates="knowledge_bases")
    agents = relationship("Agent", secondary=agent_knowledge_bases, back_populates="knowledge_bases")