from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, LargeBinary
from sqlalchemy.orm import relationship
from app.core.database import Base
import datetime

class Credential(Base):
    __tablename__ = "credentials"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True) # e.g., "OpenAI API Key", "Google Maps API Key"
    service = Column(String, index=True) # e.g., "openai", "google_maps"
    encrypted_credentials = Column(LargeBinary) # Stores the encrypted API key or secrets
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    company_id = Column(Integer, ForeignKey("companies.id"))

    company = relationship("Company", back_populates="credentials")
