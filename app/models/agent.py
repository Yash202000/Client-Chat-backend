
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    welcome_message = Column(String)
    prompt = Column(String) # System prompt for the agent
    personality = Column(String, default="helpful")
    language = Column(String, default="en")
    timezone = Column(String, default="UTC")
    credential_id = Column(Integer, ForeignKey("credentials.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"))

    company = relationship("Company", back_populates="agents")
    messages = relationship("ChatMessage", back_populates="agent")
    credential = relationship("Credential")
    webhooks = relationship("Webhook", back_populates="agent")
