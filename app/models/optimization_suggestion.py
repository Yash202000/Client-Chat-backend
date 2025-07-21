from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base
import datetime

class OptimizationSuggestion(Base):
    __tablename__ = "optimization_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    suggestion_type = Column(String, nullable=False)
    description = Column(String, nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    agent = relationship("Agent")
    company = relationship("Company")
