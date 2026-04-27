"""Agent Skills endpoint — allows updating an agent's skill tags for queue routing."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User

router = APIRouter()


class SkillsUpdate(BaseModel):
    skills: Optional[List[str]] = None  # e.g. ["billing", "technical", "spanish"]


class AgentSkillsOut(BaseModel):
    user_id: int
    skills: Optional[List[str]]

    class Config:
        from_attributes = True


@router.get("/{user_id}", response_model=AgentSkillsOut)
def get_agent_skills(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get the skills list for an agent in the current company."""
    user = db.query(User).filter(
        User.id == user_id,
        User.company_id == current_user.company_id,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentSkillsOut(user_id=user.id, skills=user.skills)


@router.patch("/{user_id}", response_model=AgentSkillsOut)
def update_agent_skills(
    user_id: int,
    payload: SkillsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update the skills list for an agent. Admin or self only."""
    user = db.query(User).filter(
        User.id == user_id,
        User.company_id == current_user.company_id,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not current_user.is_admin and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not authorised to update another agent's skills")
    user.skills = payload.skills
    db.commit()
    db.refresh(user)
    return AgentSkillsOut(user_id=user.id, skills=user.skills)
