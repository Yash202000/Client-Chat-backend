"""Instance License Model for On-Premise deployments.

This is a singleton table that stores the license for the entire installation.
Only one row can exist (enforced by id=1 constraint).
"""

from sqlalchemy import Column, Integer, Text, DateTime, JSON, CheckConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class InstanceLicense(Base):
    """
    Singleton table for storing the on-premise license.

    This model represents the license for the entire installation (not per-company).
    Only one row should ever exist in this table.
    """
    __tablename__ = "instance_licenses"

    id = Column(Integer, primary_key=True, default=1)
    license_key = Column(Text, nullable=True)
    activated_at = Column(DateTime, nullable=True)
    license_metadata = Column(JSON, nullable=True)  # Stores: max_users, features, expires_at, instance_name
    last_validated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Constraint to ensure only one row can exist
    __table_args__ = (
        CheckConstraint('id = 1', name='singleton_constraint'),
    )

    def __repr__(self):
        return f"<InstanceLicense(activated_at={self.activated_at})>"
