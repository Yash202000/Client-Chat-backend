from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from app.core.database import Base


class DataDeletionRequest(Base):
    """
    Tracks public data deletion requests — either submitted via the web form
    or triggered by Facebook's signed deletion callback.
    """
    __tablename__ = "data_deletion_requests"

    id = Column(Integer, primary_key=True, index=True)
    confirmation_code = Column(String(64), unique=True, nullable=False, index=True)

    # "user_submitted" | "facebook_callback"
    request_type = Column(String(20), nullable=False, default="user_submitted")

    # Set for user-submitted requests
    email = Column(String(255), nullable=True, index=True)
    name = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)

    # Set for Facebook callback requests (page-scoped user ID)
    facebook_user_id = Column(String(100), nullable=True, index=True)

    # "pending" | "processing" | "completed"
    status = Column(String(20), nullable=False, default="pending")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)
