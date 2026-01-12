
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from app.models import agent as models_agent, tool as models_tool, credential as models_credential, knowledge_base as models_knowledge_base
from app.schemas import agent as schemas_agent
from fastapi import HTTPException

def get_agent(db: Session, agent_id: int, company_id: int):
    return db.query(models_agent.Agent).options(
        joinedload(models_agent.Agent.tools),
        joinedload(models_agent.Agent.workflows),
        joinedload(models_agent.Agent.knowledge_bases),
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
        voice_id=agent.voice_id,
        tts_provider=agent.tts_provider,
        stt_provider=agent.stt_provider,
        company_id=company_id,
        version_number=1, # Initial version
        status="active", # New agents are active by default
        is_active=True,
        # Agent-to-agent handoff configuration
        specialization_topics=agent.specialization_topics or [],
        handoff_config=agent.handoff_config or {}
    )
    db.add(db_agent)
    db.commit()
    db.refresh(db_agent)

    # Auto-add default contact tools for new agents
    default_builtin_tools = ["get_contact_info", "create_or_update_contact"]
    for tool_name in default_builtin_tools:
        tool = db.query(models_tool.Tool).filter(
            models_tool.Tool.name == tool_name,
            models_tool.Tool.tool_type == "builtin",
            models_tool.Tool.company_id.is_(None)
        ).first()
        if tool and tool not in db_agent.tools:
            db_agent.tools.append(tool)
    db.commit()
    db.refresh(db_agent)

    # Handle additional tool_ids for initial creation
    if agent.tool_ids:
        for tool_id in agent.tool_ids:
            tool = db.query(models_tool.Tool).filter(
                models_tool.Tool.id == tool_id,
                or_(
                    models_tool.Tool.company_id == company_id,
                    models_tool.Tool.company_id.is_(None)  # Include global builtin tools
                )
            ).first()
            if tool and tool not in db_agent.tools:
                db_agent.tools.append(tool)
        db.commit()
        db.refresh(db_agent)

    # Handle knowledge_base_ids for initial creation
    if agent.knowledge_base_ids:
        for kb_id in agent.knowledge_base_ids:
            kb = db.query(models_knowledge_base.KnowledgeBase).filter(
                models_knowledge_base.KnowledgeBase.id == kb_id,
                models_knowledge_base.KnowledgeBase.company_id == company_id
            ).first()
            if kb:
                db_agent.knowledge_bases.append(kb)
        db.commit()
        db.refresh(db_agent)

    return db_agent

def update_agent(db: Session, agent_id: int, agent: schemas_agent.AgentUpdate, company_id: int):
    db_agent = db.query(models_agent.Agent).options(joinedload(models_agent.Agent.tools), joinedload(models_agent.Agent.knowledge_bases)).filter(models_agent.Agent.id == agent_id, models_agent.Agent.company_id == company_id).first()
    if db_agent:
        update_data = agent.model_dump(exclude_unset=True)
        
        # Handle tool_ids separately
        tool_ids = update_data.pop("tool_ids", None)
        if tool_ids is not None:
            db_agent.tools.clear() # Clear existing tools
            for tool_id in tool_ids:
                tool = db.query(models_tool.Tool).filter(
                    models_tool.Tool.id == tool_id,
                    or_(
                        models_tool.Tool.company_id == company_id,
                        models_tool.Tool.company_id.is_(None)  # Include global builtin tools
                    )
                ).first()
                if tool:
                    db_agent.tools.append(tool)

        # Handle knowledge_base_ids separately
        knowledge_base_ids = update_data.pop("knowledge_base_ids", None)
        print(knowledge_base_ids)
        if knowledge_base_ids is not None:
            db_agent.knowledge_bases.clear() # Clear existing knowledge bases
            for kb_id in knowledge_base_ids:
                kb = db.query(models_knowledge_base.KnowledgeBase).filter(
                    models_knowledge_base.KnowledgeBase.id == kb_id,
                    models_knowledge_base.KnowledgeBase.company_id == company_id
                ).first()
                print(kb)
                if kb:
                    db_agent.knowledge_bases.append(kb)
        print("updated knowledge bases:", db_agent.knowledge_bases)

        # Handle credential_id separately for "One API Key per Agent per Service" constraint
        if "credential_id" in update_data and update_data["credential_id"] is not None:
            new_credential_id = update_data["credential_id"]
            new_credential = db.query(models_credential.Credential).filter(models_credential.Credential.id == new_credential_id).first()
            
            if new_credential:
                # Check if agent already has a credential for this service
                existing_credential = db.query(models_credential.Credential).join(models_agent.Agent, models_agent.Agent.credential_id == models_credential.Credential.id).filter(models_agent.Agent.id == agent_id,
                        models_credential.Credential.service == new_credential.service).first()
                
                if existing_credential and existing_credential.id != new_credential_id:
                    raise HTTPException(status_code=400, detail=f"Agent already has a credential for service '{new_credential.service}'.")
        
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
        voice_id=original_agent.voice_id,
        tts_provider=original_agent.tts_provider,
        stt_provider=original_agent.stt_provider,
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

    # Copy knowledge bases from the original agent to the new version
    for kb in original_agent.knowledge_bases:
        new_version.knowledge_bases.append(kb)
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
