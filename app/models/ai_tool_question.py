
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class AIToolQuestion(Base):
    __tablename__ = "ai_tool_questions"

    id = Column(Integer, primary_key=True, index=True)
    tool_id = Column(Integer, ForeignKey("ai_tools.id"))
    question_text = Column(String)
    question_type = Column(String) # e.g., 'text', 'textarea', 'select'
    hint = Column(String, nullable=True)

    tool = relationship("AITool", back_populates="questions")
