
from sqlalchemy.orm import Session
from app.models import agent as models_agent
from app.schemas import agent as schemas_agent

def get_agent(db: Session, agent_id: int, company_id: int):
    return db.query(models_agent.Agent).filter(models_agent.Agent.id == agent_id, models_agent.Agent.company_id == company_id).first()

def get_agents(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_agent.Agent).filter(models_agent.Agent.company_id == company_id).offset(skip).limit(limit).all()

def create_agent(db: Session, agent: schemas_agent.AgentCreate, company_id: int):
    db_agent = models_agent.Agent(
        name=agent.name,
        welcome_message=agent.welcome_message,
        prompt=agent.prompt,
        personality=agent.personality,
        language=agent.language,
        timezone=agent.timezone,
        credential_id=agent.credential_id,
        company_id=company_id
    )
    db.add(db_agent)
    db.commit()
    db.refresh(db_agent)
    return db_agent

def update_agent(db: Session, agent_id: int, agent: schemas_agent.AgentUpdate, company_id: int):
    db_agent = db.query(models_agent.Agent).filter(models_agent.Agent.id == agent_id, models_agent.Agent.company_id == company_id).first()
    if db_agent:
        for key, value in agent.dict(exclude_unset=True).items():
            setattr(db_agent, key, value)
        db.commit()
        db.refresh(db_agent)
    return db_agent

def delete_agent(db: Session, agent_id: int, company_id: int):
    db_agent = db.query(models_agent.Agent).filter(models_agent.Agent.id == agent_id, models_agent.Agent.company_id == company_id).first()
    if db_agent:
        db.delete(db_agent)
        db.commit()
    return db_agent
