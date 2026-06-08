from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from app.core.database import Base
import datetime


class WebhookDeliveryLog(Base):
    __tablename__ = "webhook_delivery_logs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    webhook_id = Column(Integer, nullable=True)  # FK to webhooks.id if known
    event_type = Column(String(50))          # e.g. "message.delivered", "message.read", "message.failed"
    payload = Column(Text)                   # JSON of what was sent
    webhook_url = Column(String(500))
    status_code = Column(Integer, nullable=True)
    success = Column(Boolean, default=False)
    error_message = Column(String(500), nullable=True)
    attempt = Column(Integer, default=1)
    next_retry_at = Column(DateTime, nullable=True)  # When to next retry (None = no retry pending)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
