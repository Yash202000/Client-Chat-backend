from sqlalchemy.orm import Session
from app.models import memory as models_memory
from app.schemas import memory as schemas_memory

def set_memory(db: Session, memory_in: schemas_memory.MemoryCreate, agent_id: int, session_id: str):
    """
    Creates a new memory entry or updates an existing one (upsert).
    """
    db_memory = db.query(models_memory.Memory).filter(
        models_memory.Memory.agent_id == agent_id,
        models_memory.Memory.session_id == session_id,
        models_memory.Memory.key == memory_in.key
    ).first()

    if db_memory:
        # Update existing memory
        db_memory.value = memory_in.value
    else:
        # Create new memory
        db_memory = models_memory.Memory(**memory_in.dict(), agent_id=agent_id, session_id=session_id)
        db.add(db_memory)
    
    db.commit()
    db.refresh(db_memory)
    return db_memory

def get_memory(db: Session, agent_id: int, session_id: str, key: str):
    return db.query(models_memory.Memory).filter(
        models_memory.Memory.agent_id == agent_id,
        models_memory.Memory.session_id == session_id,
        models_memory.Memory.key == key
    ).first()

def get_all_memories(db: Session, agent_id: int, session_id: str):
    return db.query(models_memory.Memory).filter(
        models_memory.Memory.agent_id == agent_id,
        models_memory.Memory.session_id == session_id
    ).all()
