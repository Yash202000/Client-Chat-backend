
from sqlalchemy import Column, Integer, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    email_notifications_enabled = Column(Boolean, default=True)
    slack_notifications_enabled = Column(Boolean, default=False)
    auto_assignment_enabled = Column(Boolean, default=True)

    company = relationship("Company")
