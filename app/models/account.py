from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, DECIMAL
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class Account(Base):
    """CRM B2B Account (called 'Companies' in the UI). Distinct from the tenant Company model."""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)  # tenant scope

    # Core identity
    name = Column(String, nullable=False, index=True)
    domain = Column(String, nullable=True, index=True)
    industry = Column(String, nullable=True, index=True)
    employee_count = Column(Integer, nullable=True)
    annual_revenue = Column(DECIMAL(15, 2), nullable=True)

    # Contact info
    phone = Column(String, nullable=True)
    website = Column(String, nullable=True)

    # Address
    address_street = Column(String, nullable=True)
    address_city = Column(String, nullable=True)
    address_state = Column(String, nullable=True)
    address_country = Column(String, nullable=True)
    address_zip = Column(String, nullable=True)

    description = Column(Text, nullable=True)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    company = relationship("Company", back_populates="accounts")
    owner = relationship("User", back_populates="owned_accounts")
    contacts = relationship("Contact", back_populates="account")


# Back-populate on Company (tenant) and User
from app.models.company import Company
from app.models.user import User

Company.accounts = relationship("Account", back_populates="company")
User.owned_accounts = relationship("Account", back_populates="owner")
