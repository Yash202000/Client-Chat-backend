
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, func
from sqlalchemy.orm import relationship
from app.core.database import Base

class TeamMembership(Base):
    __tablename__ = "team_memberships"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    team_id = Column(Integer, ForeignKey("teams.id"))
    role = Column(String, default="member") # e.g., "admin", "member"
    company_id = Column(Integer, ForeignKey("companies.id"))

    # Agent pool management fields for handoff functionality
    is_available = Column(Boolean, default=True, server_default='true') # Agent availability for handoff assignment
    priority = Column(Integer, default=0, server_default='0') # Higher priority agents get assignments first
    max_concurrent_sessions = Column(Integer, default=3, server_default='3') # Maximum concurrent sessions
    current_session_count = Column(Integer, default=0, server_default='0') # Current active sessions

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="team_memberships")
    team = relationship("Team", back_populates="members")
    company = relationship("Company")
