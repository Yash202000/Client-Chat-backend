from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base


class TwilioPhoneNumber(Base):
    """
    Model for storing Twilio phone number configurations.

    Maps Twilio phone numbers to companies and agents for routing
    incoming voice calls to the appropriate AI agent.
    """
    __tablename__ = "twilio_phone_numbers"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=False)  # E.164 format
    friendly_name = Column(String, nullable=True)

    # Company and agent mapping
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    default_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    integration_id = Column(Integer, ForeignKey("integrations.id"), nullable=False)

    is_active = Column(Boolean, default=True)

    # Voice settings
    welcome_message = Column(String, nullable=True)  # Initial TTS message
    language = Column(String, default="en-US")

    # Relationships
    company = relationship("Company")
    default_agent = relationship("Agent")
    integration = relationship("Integration")
