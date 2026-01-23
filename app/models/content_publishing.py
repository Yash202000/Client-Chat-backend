from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.core.database import Base
import secrets


class ContentCopy(Base):
    """
    Tracks content copies/forks from marketplace.
    When a user copies content from the marketplace, a record is created here.
    """
    __tablename__ = "content_copies"

    id = Column(Integer, primary_key=True, index=True)

    # Original content
    original_item_id = Column(Integer, ForeignKey("content_items.id"), nullable=False)
    original_company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Copied content
    copied_item_id = Column(Integer, ForeignKey("content_items.id"), nullable=False)
    copied_by_company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    copied_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    copied_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    original_item = relationship("ContentItem", foreign_keys=[original_item_id], backref="copies_made")
    copied_item = relationship("ContentItem", foreign_keys=[copied_item_id], backref="copy_source")
    original_company = relationship("Company", foreign_keys=[original_company_id])
    copied_by_company = relationship("Company", foreign_keys=[copied_by_company_id])
    copied_by_user = relationship("User", backref="content_copies")


class ContentApiToken(Base):
    """
    Public API access tokens for accessing public visibility content.
    Allows external systems to query content via API.
    """
    __tablename__ = "content_api_tokens"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True)

    token = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=True)

    # Permissions
    can_read = Column(Boolean, default=True)
    can_search = Column(Boolean, default=True)
    rate_limit = Column(Integer, default=100)  # requests per minute

    # Usage tracking
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    request_count = Column(Integer, default=0)

    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    company = relationship("Company", back_populates="content_api_tokens")
    knowledge_base = relationship("KnowledgeBase", back_populates="content_api_tokens")

    @staticmethod
    def generate_token():
        """Generate a secure random token."""
        return secrets.token_urlsafe(48)


class ContentExport(Base):
    """
    Tracks content export requests and their status.
    Exported files are stored in S3.
    """
    __tablename__ = "content_exports"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True)

    format = Column(String(20), nullable=False)  # json, csv, pdf
    status = Column(String(20), default='pending')  # pending, processing, completed, failed

    s3_key = Column(String(500), nullable=True)  # export file location
    file_size = Column(Integer, nullable=True)
    item_count = Column(Integer, nullable=True)

    # Filter criteria used for export
    filter_criteria = Column(String(500), nullable=True)

    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # auto-delete after X days
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    company = relationship("Company", back_populates="content_exports")
    knowledge_base = relationship("KnowledgeBase", back_populates="content_exports")
    requester = relationship("User", backref="content_exports")
