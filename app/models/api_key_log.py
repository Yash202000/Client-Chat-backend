from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from app.core.database import Base
import datetime


class ApiKeyLog(Base):
    __tablename__ = "api_key_logs"

    id = Column(Integer, primary_key=True, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    endpoint = Column(String(200))        # e.g. "/developer/messages/send"
    method = Column(String(10))           # POST, GET
    status_code = Column(Integer)
    response_ms = Column(Integer, nullable=True)  # latency in ms
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
