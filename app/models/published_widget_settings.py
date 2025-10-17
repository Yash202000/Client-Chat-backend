import uuid
from sqlalchemy import Column, Integer, String, Boolean, JSON
from app.core.database import Base

class PublishedWidgetSettings(Base):
    __tablename__ = "published_widget_settings"

    id = Column(Integer, primary_key=True, index=True)
    publish_id = Column(String, unique=True, index=True, default=lambda: str(uuid.uuid4()))
    settings = Column(JSON)
