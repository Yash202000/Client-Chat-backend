from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Table, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


# Association tables for many-to-many relationships
lead_tags = Table(
    'lead_tags',
    Base.metadata,
    Column('lead_id', Integer, ForeignKey('leads.id', ondelete='CASCADE'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime, default=datetime.utcnow)
)

contact_tags = Table(
    'contact_tags',
    Base.metadata,
    Column('contact_id', Integer, ForeignKey('contacts.id', ondelete='CASCADE'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime, default=datetime.utcnow)
)


class Tag(Base):
    """Tag model for categorizing leads and contacts"""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    color = Column(String(7), default="#6B7280")  # Hex color code
    description = Column(String(255), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Which entity types can use this tag: 'lead', 'contact', or 'both'
    entity_type = Column(String(20), default="both", nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    company = relationship("Company", back_populates="tags")
    leads = relationship("Lead", secondary=lead_tags, back_populates="tag_objects")
    contacts = relationship("Contact", secondary=contact_tags, back_populates="tag_objects")

    # Unique constraint: tag name must be unique per company
    __table_args__ = (
        UniqueConstraint('name', 'company_id', name='uq_tag_name_company'),
    )


# Add relationships to Lead and Contact models
from app.models.lead import Lead
from app.models.contact import Contact
from app.models.company import Company

Lead.tag_objects = relationship("Tag", secondary=lead_tags, back_populates="leads")
Contact.tag_objects = relationship("Tag", secondary=contact_tags, back_populates="contacts")
Company.tags = relationship("Tag", order_by=Tag.name, back_populates="company")
