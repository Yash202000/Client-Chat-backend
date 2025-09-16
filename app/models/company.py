
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from app.core.database import Base

class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)

    users = relationship("User", back_populates="company")
    agents = relationship("Agent", back_populates="company")
    voice_profiles = relationship("VoiceProfile", back_populates="company")
    credentials = relationship("Credential", back_populates="company")
    teams = relationship("Team", back_populates="company")
    knowledge_bases = relationship("KnowledgeBase", back_populates="company")
    tools = relationship("Tool", back_populates="company")
    integrations = relationship("Integration", back_populates="company")
    chat_channels = relationship("ChatChannel", back_populates="company")
    processing_templates = relationship("ProcessingTemplate", back_populates="company")
