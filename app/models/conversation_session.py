from sqlalchemy import Column, Integer, String, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String, unique=True, index=True, nullable=False)
    
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    next_step_id = Column(String, nullable=True) # The ID of the node to execute upon resumption
    
    context = Column(JSON, nullable=False, default={}) # Stores all collected variables
    status = Column(String, nullable=False, default='active') # e.g., active, paused, completed

    workflow = relationship("Workflow")
