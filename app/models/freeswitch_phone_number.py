from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base


class FreeSwitchPhoneNumber(Base):
    """
    Model for storing FreeSWITCH phone number/extension configurations.

    Maps FreeSWITCH extensions/DIDs to companies and agents for routing
    incoming voice calls to the appropriate AI agent.
    """
    __tablename__ = "freeswitch_phone_numbers"

    id = Column(Integer, primary_key=True, index=True)
    # Can be a phone number (DID) or internal extension
    phone_number = Column(String, unique=True, index=True, nullable=False)
    friendly_name = Column(String, nullable=True)

    # Company and agent mapping
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    default_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)

    is_active = Column(Boolean, default=True)

    # Voice settings
    welcome_message = Column(String, nullable=True)  # Initial TTS message
    language = Column(String, default="en-US")

    # FreeSWITCH specific settings
    # Audio format: l16 (16-bit PCM), PCMU (G.711 μ-law), PCMA (G.711 A-law)
    audio_format = Column(String, default="l16")
    sample_rate = Column(Integer, default=8000)  # 8000, 16000, 48000

    # FreeSWITCH server connection (for multi-server setups)
    freeswitch_server = Column(String, nullable=True)  # Optional: hostname/IP of FS server

    # Relationships
    company = relationship("Company")
    default_agent = relationship("Agent")
