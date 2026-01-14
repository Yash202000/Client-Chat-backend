from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.core.database import Base


class ContentMedia(Base):
    """
    Stores metadata for uploaded media files (images, audio, video, documents).
    Actual files are stored in S3/MinIO.
    """
    __tablename__ = "content_media"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # File info
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=True)
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)  # bytes
    media_type = Column(String(20), nullable=True, index=True)  # image, audio, video, file

    # Storage
    s3_bucket = Column(String(100), nullable=True)
    s3_key = Column(String(500), nullable=False)
    thumbnail_s3_key = Column(String(500), nullable=True)  # for images/videos

    # Image/Video dimensions
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    duration = Column(Integer, nullable=True)  # seconds for audio/video

    # Metadata
    alt_text = Column(String(255), nullable=True)
    caption = Column(Text, nullable=True)

    # Usage tracking
    usage_count = Column(Integer, default=0)

    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    company = relationship("Company", back_populates="content_media")
    uploader = relationship("User", backref="uploaded_media")
