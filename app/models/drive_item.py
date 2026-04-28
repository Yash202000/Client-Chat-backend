from sqlalchemy import Column, Integer, String, Boolean, BigInteger, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.core.database import Base


class DriveItem(Base):
    __tablename__ = "drive_items"

    id         = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id   = Column(Integer, ForeignKey("users.id",     ondelete="SET NULL"), nullable=True)
    parent_id  = Column(Integer, ForeignKey("drive_items.id", ondelete="CASCADE"), nullable=True, index=True)

    name      = Column(String(255), nullable=False)
    is_folder = Column(Boolean, nullable=False, default=False)

    s3_key    = Column(String(500), nullable=True)   # null for folders
    mime_type = Column(String(100), nullable=True)
    file_size = Column(BigInteger,  nullable=True)   # bytes; null for folders

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    parent   = relationship("DriveItem", remote_side=[id], back_populates="children")
    children = relationship("DriveItem", back_populates="parent", cascade="all, delete-orphan")
    owner    = relationship("User")
