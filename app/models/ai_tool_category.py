from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from app.core.database import Base

class AIToolCategory(Base):
    __tablename__ = "ai_tool_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, unique=True)
    icon = Column(String, nullable=True)

    ai_tools = relationship("AITool", back_populates="category")