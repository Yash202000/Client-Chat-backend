
from sqlalchemy import Column, Integer, String, DateTime, func, JSON
from app.core.database import Base

class AIImage(Base):
    __tablename__ = "ai_images"

    id = Column(Integer, primary_key=True, index=True)
    prompt = Column(String, nullable=False)
    image_url = Column(String, nullable=False)
    
    # Store other generation parameters as JSON
    generation_params = Column(JSON, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
