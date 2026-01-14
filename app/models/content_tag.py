from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.core.database import Base


class ContentTag(Base):
    """
    Tags for content items.
    Tags are company-scoped and can be used across content types.
    """
    __tablename__ = "content_tags"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False, index=True)
    color = Column(String(7), nullable=True)  # hex color e.g., #FF5733

    usage_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    company = relationship("Company", back_populates="content_tags")
