from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import List
import httpx
import os

from app.schemas import chat_message as schemas_chat_message
from app.services import chat_service, credential_service, agent_service
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

@router.websocket("/ws/{company_id}/{agent_id}/{session_id}")
async def websocket_endpoint(websocket: WebSocket, company_id: int, agent_id: int, session_id: str, db: Session = Depends(get_db)):
    await websocket.accept()
    agent = agent_service.get_agent(db, agent_id, company_id)
    if not agent:
        await websocket.send_text("Agent not found")
        await websocket.close()
        return

    await websocket.send_json({"message": agent.welcome_message or f"Hello! You are connected to agent {agent.name}.", "sender": "agent"})
    
    try:
        while True:
            data = await websocket.receive_text()
            chat_service.create_chat_message(db, schemas_chat_message.ChatMessageCreate(message=data, sender="user"), agent_id, session_id, company_id, sender="user")

            # Grok integration
            response_message = "I'm sorry, I don't understand."
            try:
                api_key = None
                if agent.credential_id:
                    credential = credential_service.get_credential(db, agent.credential_id, company_id)
                    if credential:
                        api_key = credential.api_key
                    else:
                        response_message = "Error: Credential not found for this agent."
                
                if not api_key:
                    response_message = "Error: API key not configured for this agent."
                else:
                    # Fetch chat history for context
                    chat_history = chat_service.get_chat_messages(db, agent_id, session_id, company_id)
                    messages = []

                    # Add agent's prompt as a system message
                    if agent.prompt:
                        messages.append({"role": "system", "content": agent.prompt})
                    
                    # Add past messages from chat history
                    for msg in chat_history:
                        messages.append({"role": "user", "content": msg.message}) # For simplicity, treating all as user for now

                    # Add current user message
                    messages.append({"role": "user", "content": data})

                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": "llama3-8b-8192", # You can choose a different Grok model
                                "messages": messages,
                                "temperature": 0.7,
                                "max_tokens": 150,
                            },
                            timeout=30.0
                        )
                        response.raise_for_status() # Raise an exception for HTTP errors
                        grok_response = response.json()
                        response_message = grok_response["choices"][0]["message"]["content"]

            except httpx.RequestError as e:
                response_message = f"Error communicating with Grok API: {e}"
                print(response_message)
            except httpx.HTTPStatusError as e:
                response_message = f"Grok API returned an error: {e.response.status_code} - {e.response.text}"
                print(response_message)
            except Exception as e:
                response_message = f"An unexpected error occurred during Grok processing: {e}"
                print(response_message)

            chat_service.create_chat_message(db, schemas_chat_message.ChatMessageCreate(message=response_message, sender="agent"), agent_id, session_id, company_id, sender="agent")
            await websocket.send_json({"message": response_message, "sender": "agent"})

    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print(f"WebSocket Error: {e}")
