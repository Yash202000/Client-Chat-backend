from sqlalchemy import Column, Integer, String, ForeignKey, Enum, DateTime, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base
from app.models.social_account import SocialPlatform


class PostStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class SocialPost(Base):
    __tablename__ = "social_posts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    social_account_id = Column(Integer, ForeignKey("social_accounts.id"), nullable=False, index=True)
    platform = Column(Enum(SocialPlatform), nullable=False, index=True)  # denormalized for fast queries

    content = Column(Text, nullable=False)
    media_urls = Column(JSONB, nullable=True)               # list of image/video URLs
    hashtags = Column(JSONB, nullable=True)                 # extracted hashtag list

    status = Column(Enum(PostStatus), default=PostStatus.DRAFT, nullable=False, index=True)
    scheduled_at = Column(DateTime, nullable=True, index=True)
    published_at = Column(DateTime, nullable=True)
    platform_post_id = Column(String, nullable=True)        # ID returned by platform after publish
    error_message = Column(Text, nullable=True)

    # AI generation metadata
    ai_generated = Column(Boolean, default=False, nullable=False)
    source_topic = Column(String, nullable=True)            # topic prompt used for generation
    source_url = Column(String, nullable=True)              # trending post URL that inspired it

    # Analytics (populated by polling platform APIs)
    likes = Column(Integer, default=0, nullable=False)
    comments = Column(Integer, default=0, nullable=False)
    shares = Column(Integer, default=0, nullable=False)
    impressions = Column(Integer, default=0, nullable=False)
    analytics_updated_at = Column(DateTime, nullable=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    social_account = relationship("SocialAccount", back_populates="posts")
    company = relationship("Company", back_populates="social_posts")


# Back-populate on Company
from app.models.company import Company
Company.social_posts = relationship("SocialPost", back_populates="company")
