
from sqlalchemy.orm import Session, joinedload
from app.models import agent as models_agent, tool as models_tool
from app.schemas import agent as schemas_agent

def get_agent(db: Session, agent_id: int, company_id: int):
    return db.query(models_agent.Agent).options(
        joinedload(models_agent.Agent.tools), 
        joinedload(models_agent.Agent.workflows),
        joinedload(models_agent.Agent.credential)  # Eagerly load the credential
    ).filter(models_agent.Agent.id == agent_id, models_agent.Agent.company_id == company_id).first()

def get_agents(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_agent.Agent).filter(models_agent.Agent.company_id == company_id).offset(skip).limit(limit).all()

def create_agent(db: Session, agent: schemas_agent.AgentCreate, company_id: int):
    db_agent = models_agent.Agent(
        name=agent.name,
        welcome_message=agent.welcome_message,
        prompt=agent.prompt,
        llm_provider=agent.llm_provider,
        model_name=agent.model_name,
        personality=agent.personality,
        language=agent.language,
        timezone=agent.timezone,
        response_style=agent.response_style,
        instructions=agent.instructions,
        credential_id=agent.credential_id,
        knowledge_base_id=agent.knowledge_base_id,
        company_id=company_id,
        version_number=1, # Initial version
        status="active", # New agents are active by default
        is_active=True
    )
    db.add(db_agent)
    db.commit()
    db.refresh(db_agent)

    # Handle tool_ids for initial creation
    if agent.tool_ids:
        for tool_id in agent.tool_ids:
            tool = db.query(models_tool.Tool).filter(models_tool.Tool.id == tool_id, models_tool.Tool.company_id == company_id).first()
            if tool:
                db_agent.tools.append(tool)
        db.commit()
        db.refresh(db_agent)

    return db_agent

def update_agent(db: Session, agent_id: int, agent: schemas_agent.AgentUpdate, company_id: int):
    db_agent = db.query(models_agent.Agent).filter(models_agent.Agent.id == agent_id, models_agent.Agent.company_id == company_id).first()
    if db_agent:
        update_data = agent.dict(exclude_unset=True)
        
        # Handle tool_ids separately
        tool_ids = update_data.pop("tool_ids", None)
        if tool_ids is not None:
            db_agent.tools.clear() # Clear existing tools
            for tool_id in tool_ids:
                tool = db.query(models_tool.Tool).filter(models_tool.Tool.id == tool_id, models_tool.Tool.company_id == company_id).first()
                if tool:
                    db_agent.tools.append(tool)

        for key, value in update_data.items():
            setattr(db_agent, key, value)
            
        db.commit()
        db.refresh(db_agent)
    return db_agent

def create_agent_version(db: Session, agent_id: int, company_id: int):
    original_agent = get_agent(db, agent_id, company_id)
    if not original_agent:
        raise ValueError("Original agent not found.")

    # Archive the current active version if it's not already a draft
    if original_agent.status == "active":
        original_agent.status = "archived"
        db.add(original_agent)
        db.commit()
        db.refresh(original_agent)

    # Create a new version based on the original
    new_version = models_agent.Agent(
        name=original_agent.name, # Name remains the same
        welcome_message=original_agent.welcome_message,
        prompt=original_agent.prompt,
        llm_provider=original_agent.llm_provider,
        model_name=original_agent.model_name,
        personality=original_agent.personality,
        language=original_agent.language,
        timezone=original_agent.timezone,
        is_active=False, # New versions are inactive by default
        response_style=original_agent.response_style,
        instructions=original_agent.instructions,
        credential_id=original_agent.credential_id,
        knowledge_base_id=original_agent.knowledge_base_id,
        company_id=company_id,
        version_number=original_agent.version_number + 1, # Increment version
        parent_version_id=original_agent.id, # Link to parent
        status="draft" # New version starts as a draft
    )
    db.add(new_version)
    db.commit()
    db.refresh(new_version)

    # Copy tools from the original agent to the new version
    for tool in original_agent.tools:
        new_version.tools.append(tool)
    db.commit()
    db.refresh(new_version)

    return new_version

def activate_agent_version(db: Session, agent_id: int, company_id: int):
    agent_to_activate = get_agent(db, agent_id, company_id)
    if not agent_to_activate:
        raise ValueError("Agent version not found.")

    # Find all agents with the same name and company_id
    # and set their status to 'archived' if they are 'active'
    agents_with_same_name = db.query(models_agent.Agent).filter(
        models_agent.Agent.name == agent_to_activate.name,
        models_agent.Agent.company_id == company_id,
        models_agent.Agent.status == "active"
    ).all()

    for agent in agents_with_same_name:
        agent.status = "archived"
        agent.is_active = False
        db.add(agent)

    # Set the chosen agent version to active
    agent_to_activate.status = "active"
    agent_to_activate.is_active = True
    db.add(agent_to_activate)
    db.commit()
    db.refresh(agent_to_activate)

    return agent_to_activate

def delete_agent(db: Session, agent_id: int, company_id: int):
    db_agent = db.query(models_agent.Agent).filter(models_agent.Agent.id == agent_id, models_agent.Agent.company_id == company_id).first()
    if db_agent:
        db.delete(db_agent)
        db.commit()
    return db_agent
