from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import httpx
import os

from app.schemas import chat_message as schemas_chat_message
from app.services import chat_service, credential_service, agent_service, knowledge_base_service
from app.core.dependencies import get_db, get_current_company
from app.core.config import settings
from app.models import credential as models_credential

router = APIRouter()

@router.get("/{agent_id}/sessions", response_model=List[str])
def get_agent_sessions(agent_id: int, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    sessions = chat_service.get_unique_session_ids_for_agent(db, agent_id=agent_id, company_id=current_company_id)
    return [session[0] for session in sessions]

@router.get("/{agent_id}/sessions/{session_id}/messages", response_model=List[schemas_chat_message.ChatMessage])
def get_session_messages(agent_id: int, session_id: str, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company), skip: int = 0, limit: int = 100):
    messages = chat_service.get_chat_messages(db, agent_id=agent_id, session_id=session_id, company_id=current_company_id, skip=skip, limit=limit)
    return messages
