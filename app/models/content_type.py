from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class ContentType(Base):
    """
    Defines the schema for a content type (e.g., Shloka, Recipe, Product).
    The field_schema JSONB column stores the field definitions.
    """
    __tablename__ = "content_types"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True)

    name = Column(String(100), nullable=False)  # "Shloka", "Recipe"
    slug = Column(String(100), nullable=False, index=True)  # "shloka", "recipe"
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=True)  # lucide icon name

    # Field schema (defines what fields this content type has)
    # Example: [{"slug": "verse_text", "name": "Verse Text", "type": "rich_text", "required": true, "searchable": true}]
    field_schema = Column(JSONB, nullable=False, default=list)

    # Publishing settings
    allow_public_publish = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="content_types")
    knowledge_base = relationship("KnowledgeBase", back_populates="content_types")
    content_items = relationship("ContentItem", back_populates="content_type", cascade="all, delete-orphan")

    __table_args__ = (
        # Unique constraint: each company can only have one content type with a given slug
        {"sqlite_autoincrement": True},
    )
