from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class CustomFieldDefinition(Base):
    """
    Company-scoped typed field definitions for tickets, leads, deals, contacts.
    Values are stored in the entity's custom_fields JSONB column.
    """
    __tablename__ = "custom_field_definitions"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Which entity this field applies to
    entity_type = Column(String, nullable=False, index=True)  # ticket|lead|deal|contact

    # Field identity
    name = Column(String, nullable=False)          # machine key used in custom_fields JSONB
    label = Column(String, nullable=False)         # human-readable label shown in UI

    # Field type controls the input rendered
    # text|number|decimal|boolean|date|datetime|dropdown|multi_select|user_picker|url|email|phone|textarea
    field_type = Column(String, nullable=False, default="text")

    # For dropdown / multi_select: list of {value, label, color?}
    options = Column(JSONB, nullable=True)

    required = Column(Boolean, default=False, nullable=False)
    default_value = Column(JSONB, nullable=True)    # must match field_type

    # Display order within entity type
    position = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True, nullable=False)

    # Optional grouping / section header in UI
    group_name = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", backref="custom_field_definitions")
