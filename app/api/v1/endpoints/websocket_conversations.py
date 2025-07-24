from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.orm import Session
from app.services import chat_service, workflow_service, agent_execution_service, messaging_service, integration_service
from app.services.workflow_execution_service import WorkflowExecutionService
from app.schemas import chat_message as schemas_chat_message
import json
from typing import List, Dict, Any
from app.core.dependencies import get_current_user_from_ws, get_db
from app.models import user as models_user, conversation_session as models_conversation_session

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[Dict[str, Any]]] = {}

    async def connect(self, websocket: WebSocket, session_id: str, user_type: str):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append({"websocket": websocket, "user_type": user_type})

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_connections:
            connection_to_remove = next((c for c in self.active_connections[session_id] if c["websocket"] == websocket), None)
            if connection_to_remove:
                self.active_connections[session_id].remove(connection_to_remove)
                if not self.active_connections[session_id]:
                    del self.active_connections[session_id]

    async def broadcast_to_session(self, session_id: str, message: str, sender_type: str):
        print(f"[ConnectionManager] Broadcasting to session {session_id}. Message: {message[:50]}...")
        if session_id in self.active_connections:
            message_data = json.loads(message)
            if message_data.get('message_type') == 'note':
                connections_to_send = [c for c in self.active_connections[session_id] if c["user_type"] == "agent"]
                print(f"[ConnectionManager] Sending note to {len(connections_to_send)} agent connections in session {session_id}")
            else:
                connections_to_send = self.active_connections[session_id]
                print(f"[ConnectionManager] Sending message to {len(connections_to_send)} connections in session {session_id}")
            
            for connection in connections_to_send:
                try:
                    await connection["websocket"].send_text(message)
                    print(f"[ConnectionManager] Sent message to websocket: {connection["websocket"]}")
                except Exception as e:
                    print(f"[ConnectionManager] Error sending message to websocket: {e}")
                    # Optionally remove broken connection
                    # self.active_connections[session_id].remove(connection)
        else:
            print(f"[ConnectionManager] No active connections for session {session_id}")

manager = ConnectionManager()

@router.websocket("/{agent_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    agent_id: int,
    session_id: str,
    user_type: str = Query(...), # 'user' or 'agent'
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_user_from_ws)
):
    company_id = current_user.company_id # Get company_id from authenticated user
    print(f"[websocket_conversations] Attempting WebSocket connection for session: {session_id}, user: {current_user.email}, company_id: {company_id}")

    await manager.connect(websocket, session_id, user_type)
    print(f"[websocket_conversations] WebSocket connection established for session: {session_id}")
    # Instantiate the execution service
    workflow_exec_service = WorkflowExecutionService(db)
    
    try:
        while True:
            data = await websocket.receive_text()
            print(f"[websocket_conversations] Received data from frontend: {data}")
            if not data:
                continue
            
            try:
                message_data = json.loads(data)
                user_message = message_data.get('message')
                sender = message_data.get('sender')
            except (json.JSONDecodeError, AttributeError):
                print(f"[websocket_conversations] Received invalid data from session #{session_id}: {data}")
                continue

            if not user_message or not sender:
                print(f"[websocket_conversations] Missing user_message or sender: user_message={user_message}, sender={sender}")
                continue

            # 1. Log user message
            chat_message = schemas_chat_message.ChatMessageCreate(message=user_message, message_type=message_data.get('message_type', 'message'))
            db_message = chat_service.create_chat_message(db, chat_message, agent_id, session_id, company_id, sender)
            print(f"[websocket_conversations] Created chat message: {db_message.id}")
            await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.from_orm(db_message).json(), sender)
            print(f"[websocket_conversations] Broadcasted message to session: {session_id}")

            # If agent sends message, check session channel and send to external platform
            if sender == 'agent':
                session_obj = db.query(models_conversation_session.ConversationSession).filter(
                    models_conversation_session.ConversationSession.conversation_id == session_id,
                    models_conversation_session.ConversationSession.company_id == company_id
                ).first()
                
                if session_obj and session_obj.channel == 'whatsapp':
                    # Retrieve WhatsApp credentials for the company
                    # This part needs to be implemented based on your credential management
                    # For now, let's assume you have a way to get api_token and phone_number_id
                    # from your settings or integration service.
                    # Placeholder for actual credential retrieval
                    whatsapp_integration = integration_service.get_integration_by_type_and_company(db, "whatsapp", company_id)

                    if whatsapp_integration:
                        try:
                            # Decrypt credentials to get api_token and phone_number_id
                            whatsapp_credentials = integration_service.get_decrypted_credentials(whatsapp_integration)
                            api_token = whatsapp_credentials.get("api_token")
                            phone_number_id = whatsapp_credentials.get("phone_number_id")

                            if not api_token or not phone_number_id:
                                print(f"[websocket_conversations] WhatsApp credentials missing for company {company_id}")
                                return

                            await messaging_service.send_whatsapp_message(
                                recipient_phone_number=session_obj.contact.phone_number,
                                message_text=user_message,
                                integration=whatsapp_integration
                            )
                            print(f"[websocket_conversations] Sent message to WhatsApp for session {session_id}")
                        except Exception as e:
                            print(f"[websocket_conversations] Error sending to WhatsApp: {e}")

            # 2. If the message is from the user, execute the workflow
            if sender == 'user':
                # Use the similarity search to find the most relevant workflow
                workflow = workflow_service.find_similar_workflow(
                    db, 
                    company_id=company_id, 
                    query=user_message
                )

                if not workflow:
                    # If no specific workflow matches, provide a generic response
                    print(f"[websocket_conversations] No specific workflow found for message: '{user_message}'")
                    agent_response_text = agent_execution_service.generate_agent_response(
                        db, agent_id, session_id, company_id, message_data['message']
                    )
                    agent_message = schemas_chat_message.ChatMessageCreate(message=agent_response_text, message_type="message")
                    db_agent_message = chat_service.create_chat_message(db, agent_message, agent_id, session_id, company_id, "agent")
                    await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(), "agent")
                    print(f"[websocket_conversations] Broadcasted agent response to session: {session_id}")
                    continue

                # 3. Execute the matched workflow with the current state (conversation_id)
                execution_result = workflow_exec_service.execute_workflow(
                    workflow=workflow,
                    user_message=user_message,
                    conversation_id=session_id # Use the session_id from the URL as the conversation_id
                )

                # 4. Handle the execution result
                if execution_result.get("status") == "completed":
                    agent_response_text = execution_result.get("response", "Workflow finished.")
                    agent_message = schemas_chat_message.ChatMessageCreate(message=agent_response_text, message_type="message")
                    db_agent_message = chat_service.create_chat_message(db, agent_message, agent_id, session_id, company_id, "agent")
                    await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(), "agent")
                    print(f"[websocket_conversations] Broadcasted workflow completion to session: {session_id}")
                
                elif execution_result.get("status") == "paused_for_prompt":
                    # The workflow is paused and wants to prompt the user.
                    # We construct a special message to send to the frontend.
                    prompt_data = execution_result.get("prompt", {})
                    prompt_message = {
                        "message": prompt_data.get("text"),
                        "message_type": "prompt", # A custom type for the frontend to recognize
                        "options": prompt_data.get("options", []),
                        "sender": "agent",
                        "session_id": session_id,
                        "agent_id": agent_id,
                        "company_id": company_id,
                    }
                    # This message is not saved to the database, it's a transient prompt
                    await manager.broadcast_to_session(session_id, json.dumps(prompt_message), "agent")
                    print(f"[websocket_conversations] Broadcasted prompt to session: {session_id}")

                # If the status is "paused_for_input", we do nothing and just wait for the next user message.

    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
        print(f"Client in session #{session_id} disconnected")
