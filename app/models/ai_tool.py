from sqlalchemy import Column, Integer, String, ForeignKey, Table, Text, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

ai_tool_favorites = Table(
    'ai_tool_favorites',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('ai_tool_id', Integer, ForeignKey('ai_tools.id'), primary_key=True)
)

class AITool(Base):
    __tablename__ = "ai_tools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    category_id = Column(Integer, ForeignKey("ai_tool_categories.id"))
    likes = Column(Integer, default=0)
    views = Column(Integer, default=0)

    category = relationship("AIToolCategory", back_populates="ai_tools")
    questions = relationship("AIToolQuestion", back_populates="tool")
    favorited_by = relationship("User", secondary=ai_tool_favorites)