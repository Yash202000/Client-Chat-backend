from sqlalchemy import Column, Integer, String, ForeignKey, Enum, DateTime, LargeBinary
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class SocialPlatform(str, enum.Enum):
    LINKEDIN = "linkedin"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    REDDIT = "reddit"
    TWITTER = "twitter"


class SocialAccountStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    DISCONNECTED = "disconnected"


class SocialAccount(Base):
    __tablename__ = "social_accounts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    platform = Column(Enum(SocialPlatform), nullable=False, index=True)
    account_name = Column(String, nullable=False)           # display name shown in UI
    account_id = Column(String, nullable=False)             # platform UID / page ID / org URN
    account_type = Column(String, nullable=True)            # "personal" | "page" | "organization"

    # Encrypted credentials via vault_service (same pattern as Integration model)
    credentials = Column(LargeBinary, nullable=False)

    status = Column(Enum(SocialAccountStatus), default=SocialAccountStatus.ACTIVE, nullable=False)
    token_expires_at = Column(DateTime, nullable=True)
    scopes = Column(JSONB, nullable=True)                   # list of granted OAuth scopes
    metadata_ = Column(JSONB, nullable=True)                # followers_count, avatar_url, etc.

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="social_accounts")
    posts = relationship("SocialPost", back_populates="social_account", cascade="all, delete-orphan")


# Back-populate on Company
from app.models.company import Company
Company.social_accounts = relationship("SocialAccount", back_populates="company")
