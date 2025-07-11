
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from app.core.database import Base

class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    company_id = Column(Integer, ForeignKey("companies.id"))

    # Example setting
    dark_mode = Column(Boolean, default=False)

    owner = relationship("User", back_populates="settings")
    company = relationship("Company")
