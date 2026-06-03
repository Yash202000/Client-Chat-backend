from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.core.database import Base


class CODChannel(str, enum.Enum):
    WHATSAPP = "whatsapp"
    SMS = "sms"


class CODStatus(str, enum.Enum):
    PENDING = "pending"       # message sent, waiting for reply
    CONFIRMED = "confirmed"   # customer replied YES
    CANCELLED = "cancelled"   # customer replied NO
    EXPIRED = "expired"       # no reply within timeout
    FAILED = "failed"         # could not send message


class CODVerification(Base):
    __tablename__ = "cod_verifications"

    id = Column(Integer, primary_key=True, index=True)
    verification_id = Column(String(64), unique=True, index=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Order details
    order_id = Column(String(255), nullable=False, index=True)  # merchant's own order ID
    order_amount = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(10), default="INR", nullable=False)
    customer_name = Column(String(255), nullable=True)

    # Contact info
    channel = Column(Enum(CODChannel), nullable=False)
    recipient = Column(String(255), nullable=False)  # phone number

    # Status tracking
    status = Column(Enum(CODStatus), default=CODStatus.PENDING, nullable=False)
    customer_reply = Column(String(50), nullable=True)  # raw reply text
    expires_at = Column(DateTime, nullable=False)
    replied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Webhook to notify merchant on reply
    webhook_url = Column(String(500), nullable=True)

    # Extra data (product name, etc.)
    extra_data = Column(JSONB, nullable=True)

    company = relationship("Company", foreign_keys=[company_id])
