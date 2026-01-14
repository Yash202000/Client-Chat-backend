from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Numeric, Text, func, Table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


# Junction table for content items and categories (many-to-many)
content_item_categories = Table(
    'content_item_categories',
    Base.metadata,
    Column('content_item_id', Integer, ForeignKey('content_items.id', ondelete='CASCADE'), primary_key=True),
    Column('category_id', Integer, ForeignKey('content_categories.id', ondelete='CASCADE'), primary_key=True)
)


class ContentItem(Base):
    """
    Stores dynamic content data in JSONB.
    All custom fields are stored in the 'data' column.
    """
    __tablename__ = "content_items"

    id = Column(Integer, primary_key=True, index=True)
    content_type_id = Column(Integer, ForeignKey("content_types.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True)

    # All dynamic fields stored here as JSONB
    data = Column(JSONB, nullable=False, default=dict)

    # Status & Visibility
    status = Column(String(20), default='draft', index=True)  # draft, published, archived
    visibility = Column(String(20), default='private', index=True)  # private, company, marketplace, public

    # For marketplace
    is_featured = Column(Boolean, default=False)
    download_count = Column(Integer, default=0)
    rating = Column(Numeric(2, 1), nullable=True)

    # Versioning
    version = Column(Integer, default=1)

    # ChromaDB reference for semantic search
    chroma_doc_id = Column(String(100), nullable=True)

    # Metadata
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    content_type = relationship("ContentType", back_populates="content_items")
    company = relationship("Company", back_populates="content_items")
    knowledge_base = relationship("KnowledgeBase", back_populates="content_items")
    creator = relationship("User", foreign_keys=[created_by], backref="created_content_items")
    updater = relationship("User", foreign_keys=[updated_by], backref="updated_content_items")
    categories = relationship("ContentCategory", secondary=content_item_categories, back_populates="content_items")
