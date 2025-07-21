from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.schemas import agent as schemas_agent
from app.services import agent_service
from app.core.dependencies import get_db, get_current_company, get_current_active_user
from app.models import user as models_user


router = APIRouter()

@router.post("/", response_model=schemas_agent.Agent)
def create_agent(agent: schemas_agent.AgentCreate, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company), current_user: models_user.User = Depends(get_current_active_user)):
    return agent_service.create_agent(db=db, agent=agent, company_id=current_company_id)

@router.get("/", response_model=List[schemas_agent.Agent])
def read_agents(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company), current_user: models_user.User = Depends(get_current_active_user)):
    agents = agent_service.get_agents(db, company_id=current_company_id, skip=skip, limit=limit)
    return agents

@router.get("/{agent_id}", response_model=schemas_agent.Agent)
def read_agent(agent_id: int, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company), current_user: models_user.User = Depends(get_current_active_user)):
    db_agent = agent_service.get_agent(db, agent_id=agent_id, company_id=current_company_id)
    if db_agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return db_agent

@router.put("/{agent_id}", response_model=schemas_agent.Agent)
def update_agent(agent_id: int, agent: schemas_agent.AgentUpdate, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company), current_user: models_user.User = Depends(get_current_active_user)):
    db_agent = agent_service.update_agent(db, agent_id=agent_id, agent=agent, company_id=current_company_id)
    if db_agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return db_agent

@router.delete("/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company), current_user: models_user.User = Depends(get_current_active_user)):
    db_agent = agent_service.delete_agent(db, agent_id=agent_id, company_id=current_company_id)
    if db_agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"message": "Agent deleted successfully"}
