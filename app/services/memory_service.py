from sqlalchemy.orm import Session
from app.models import memory as models_memory
from app.schemas import memory as schemas_memory

def create_memory(db: Session, memory: schemas_memory.MemoryCreate, agent_id: int, session_id: str):
    db_memory = models_memory.Memory(**memory.dict(), agent_id=agent_id, session_id=session_id)
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
