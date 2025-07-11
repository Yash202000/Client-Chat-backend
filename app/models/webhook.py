from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    url = Column(String)
    trigger_event = Column(String) # e.g., "new_message", "conversation_end"
    is_active = Column(Boolean, default=True)
    agent_id = Column(Integer, ForeignKey("agents.id"))
    company_id = Column(Integer, ForeignKey("companies.id"))

    agent = relationship("Agent", back_populates="webhooks")
    company = relationship("Company")
