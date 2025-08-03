
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
import datetime

from app.core.database import Base

class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"))
    workflow_node_id = Column(String, nullable=False) # The ID of the node in the workflow
    workflow_id = Column(Integer, ForeignKey("workflows.id"))

    user = relationship("User")
    workflow = relationship("Workflow")
