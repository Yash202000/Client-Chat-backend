
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class TeamMembership(Base):
    __tablename__ = "team_memberships"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    team_id = Column(Integer, ForeignKey("teams.id"))
    role = Column(String, default="member") # e.g., "admin", "member"
    company_id = Column(Integer, ForeignKey("companies.id"))

    user = relationship("User", back_populates="team_memberships")
    team = relationship("Team", back_populates="members")
    company = relationship("Company")
