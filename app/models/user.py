
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    company_id = Column(Integer, ForeignKey("companies.id"))

    company = relationship("Company", back_populates="users")
    settings = relationship("UserSettings", back_populates="owner", uselist=False)
    team_memberships = relationship("TeamMembership", back_populates="user")
