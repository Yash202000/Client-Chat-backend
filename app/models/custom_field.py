from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, UniqueConstraint
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

    entity_type = Column(String, nullable=False, index=True)  # ticket|lead|deal|contact
    name = Column(String, nullable=False)
    label = Column(String, nullable=False)
    field_type = Column(String, nullable=False, default="text")
    options = Column(JSONB, nullable=True)
    required = Column(Boolean, default=False, nullable=False)
    default_value = Column(JSONB, nullable=True)
    position = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    group_name = Column(String, nullable=True)

    # True = show in all projects; False = only in projects with a config row
    is_global = Column(Boolean, default=True, nullable=False, server_default="true")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", backref="custom_field_definitions")
    project_configs = relationship("CustomFieldProjectConfig", back_populates="field", cascade="all, delete-orphan")


class CustomFieldProjectConfig(Base):
    """
    Per-project configuration for a custom field.
    Controls visibility, required override, position/group overrides.
    A non-global field only appears in projects that have a config row with visible=True.
    """
    __tablename__ = "custom_field_project_configs"
    __table_args__ = (UniqueConstraint("field_id", "project_id", name="uq_cfpc_field_project"),)

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    field_id = Column(Integer, ForeignKey("custom_field_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("ticket_projects.id", ondelete="CASCADE"), nullable=False, index=True)

    visible = Column(Boolean, nullable=False, default=True)
    required = Column(Boolean, nullable=True)    # NULL = inherit from field def
    position = Column(Integer, nullable=True)    # NULL = inherit from field def
    group_name = Column(String, nullable=True)   # NULL = inherit from field def

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    field = relationship("CustomFieldDefinition", back_populates="project_configs")
    project = relationship("TicketProject")
