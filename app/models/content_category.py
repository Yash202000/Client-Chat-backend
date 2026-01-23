from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.content_item import content_item_categories


class ContentCategory(Base):
    """
    Hierarchical categories for organizing content.
    Supports parent-child relationships for nested categories.
    """
    __tablename__ = "content_categories"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True)

    parent_id = Column(Integer, ForeignKey("content_categories.id"), nullable=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=True)

    display_order = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="content_categories")
    knowledge_base = relationship("KnowledgeBase", back_populates="content_categories")
    parent = relationship("ContentCategory", remote_side=[id], backref="children")
    content_items = relationship("ContentItem", secondary=content_item_categories, back_populates="categories")
