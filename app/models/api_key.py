from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base
import datetime

class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # New fields for API channel support
    expires_at = Column(DateTime, nullable=True)
    scopes = Column(JSON, nullable=True)  # e.g., ["messages:read", "messages:write", "sessions:manage"]
    last_used_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    company = relationship("Company")
