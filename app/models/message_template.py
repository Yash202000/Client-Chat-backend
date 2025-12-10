from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class TemplateScope(str, enum.Enum):
    """Scope of template visibility"""
    PERSONAL = "personal"  # Only visible to creator
    SHARED = "shared"      # Visible to all in company


class MessageTemplate(Base):
    """
    Pre-built message templates for quick replies in chat.
    Separate from campaign templates - focused on agent productivity.

    Features:
    - Slash command shortcuts for quick access
    - Variable replacement ({{contact_name}}, {{agent_name}}, etc.)
    - Personal vs shared scope
    - Usage tracking
    - Tag-based organization
    """
    __tablename__ = "message_templates"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Basic info
    name = Column(String(255), nullable=False)  # Display name
    shortcut = Column(String(50), nullable=False, index=True)  # Slash command (e.g., "greeting", "intro")
    content = Column(Text, nullable=False)  # Template content with variables

    # Organization
    tags = Column(ARRAY(String(50)), nullable=True, default=[])  # e.g., ["greeting", "support", "sales"]

    # Permissions
    scope = Column(Enum(TemplateScope), default=TemplateScope.PERSONAL, nullable=False, index=True)

    # Usage tracking
    usage_count = Column(Integer, default=0, nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    company = relationship("Company", backref="message_templates")
    created_by = relationship("User", backref="created_message_templates")

    def __repr__(self):
        return f"<MessageTemplate(id={self.id}, shortcut='{self.shortcut}', name='{self.name}')>"
