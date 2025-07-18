from sqlalchemy import Column, Integer, String, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    agent_id = Column(Integer, ForeignKey("agents.id"))
    steps = Column(JSON) # Stores the sequence of tool executions and logic
    visual_steps = Column(Text, nullable=True) # Stores the React Flow JSON for visual representation

    agent = relationship("Agent", back_populates="workflows")
