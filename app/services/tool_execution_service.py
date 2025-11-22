import traceback
import asyncio
import anyio
from sqlalchemy.orm import Session
from app.models.tool import Tool
from app.models.agent import Agent
from app.services import workflow_service, agent_assignment_service, conversation_session_service
from fastmcp.client import Client

def execute_custom_tool(db: Session, tool: Tool, company_id: int, session_id: str, parameters: dict):
    """
    Executes a custom tool by running its stored Python code.
    """
    if not tool.code:
        return {"error": "Tool has no code to execute."}

    local_scope = {}
    execution_globals = {
        "workflow_service": workflow_service,
        "workflow_execution_service": "workflow_execution_service" # Placeholder
    }
    
    try:
        exec(tool.code, execution_globals, local_scope)
        tool_function = local_scope.get("run")
        
        if not callable(tool_function):
            return {"error": "Tool code does not define a callable 'run' function"}

        config = {
            "db": db,
            "company_id": company_id,
            "session_id": session_id
        }

        result = tool_function(params=parameters, config=config)
        return {"result": result}

    except Exception as e:
        return {
            "error": "An error occurred during custom tool execution.",
            "details": str(e),
            "traceback": traceback.format_exc()
        }

async def execute_mcp_tool(db_tool: Tool, mcp_tool_name: str, parameters: dict):
    """
    Executes a specific tool on a remote MCP server.
    """
    mcp_server_url = db_tool.mcp_server_url
    actual_params = parameters or {}

    print(f"DEBUG: Attempting to connect to MCP server at {mcp_server_url}")
    try:
        async with Client(mcp_server_url) as client:
            print(f"DEBUG: Connected to MCP server. Calling tool '{mcp_tool_name}' with params: {actual_params}")
            if actual_params:
                result = await client.call_tool(mcp_tool_name, arguments={"params": actual_params})
            else:
                result = await client.call_tool(mcp_tool_name)
            print(f"DEBUG: MCP tool call returned: {result}")
        return {"result": result}
    except Exception as e:
        print(f"ERROR: An unexpected error occurred during MCP tool execution: {e}")
        print(traceback.format_exc())
        return {
            "error": f"An error occurred on MCP server {mcp_server_url} while running tool '{mcp_tool_name}'.",
            "details": str(e)
        }


async def execute_handoff_tool(db: Session, session_id: str, parameters: dict):
    """
    Executes the built-in handoff tool to transfer conversation to a human agent.

    Args:
        db: Database session
        session_id: Conversation session ID
        parameters: Tool parameters (reason, summary, priority, pool)

    Returns:
        Dictionary with handoff result
    """
    reason = parameters.get("reason", "customer_request")
    summary = parameters.get("summary", "")
    priority = parameters.get("priority", "normal")

    # Get the session to find the agent
    session = conversation_session_service.get_session(db, session_id)
    if not session or not session.agent_id:
        print(f"[HANDOFF TOOL] Session or agent not found for session_id: {session_id}")
        team_name = "Support"  # Default fallback
    else:
        # Get the agent to find the configured handoff team
        agent = db.query(Agent).filter(Agent.id == session.agent_id).first()
        if agent and agent.handoff_team_id and agent.handoff_team:
            team_name = agent.handoff_team.name
            print(f"[HANDOFF TOOL] Using agent's configured team: {team_name}")
        else:
            # Use parameter if provided, otherwise default to "Support"
            team_name = parameters.get("pool", "Support")
            print(f"[HANDOFF TOOL] Agent has no configured team, using: {team_name}")

    print(f"[HANDOFF TOOL] Session: {session_id}, Reason: {reason}, Team: {team_name}, Priority: {priority}")
    print(f"[HANDOFF TOOL] Summary: {summary}")

    try:
        # Request handoff via assignment service
        handoff_result = await agent_assignment_service.request_handoff(
            db=db,
            session_id=session_id,
            reason=reason,
            team_name=team_name,
            priority=priority
        )

        # Add summary to context
        handoff_result["summary"] = summary

        print(f"[HANDOFF TOOL] Result: {handoff_result}")
        return {"result": handoff_result}

    except Exception as e:
        print(f"[HANDOFF TOOL] Error: {e}")
        return {
            "error": "An error occurred while processing handoff request.",
            "details": str(e),
            "traceback": traceback.format_exc()
        }


async def execute_create_or_update_contact_tool(db: Session, session_id: str, company_id: int, parameters: dict):
    """
    Executes the built-in create_or_update_contact tool.
    Creates or updates a contact and links it to the current conversation session.

    Args:
        db: Database session
        session_id: Conversation session ID
        company_id: Company ID
        parameters: Tool parameters (name, email, phone_number)

    Returns:
        Dictionary with contact creation/update result
    """
    from app.services import contact_service
    from app.schemas.contact import ContactCreate, ContactUpdate
    from app.schemas.conversation_session import ConversationSessionUpdate

    name = parameters.get("name")
    email = parameters.get("email")
    phone_number = parameters.get("phone_number")

    # Validate that at least one field is provided
    if not name and not email and not phone_number:
        return {
            "error": "At least one of name, email, or phone_number must be provided"
        }

    print(f"[CREATE/UPDATE CONTACT TOOL] Session: {session_id}, Name: {name}, Email: {email}, Phone: {phone_number}")

    try:
        # Get the session
        session = conversation_session_service.get_session_by_conversation_id(db, session_id, company_id)
        if not session:
            return {"error": "Session not found"}

        contact = None
        updated = False

        # Check if session already has a contact
        if session.contact_id:
            # Update existing contact
            contact = contact_service.get_contact(db, session.contact_id, company_id)
            if contact:
                # Prepare update data
                update_data = {}
                if name:
                    update_data["name"] = name
                if email:
                    update_data["email"] = email
                if phone_number:
                    update_data["phone_number"] = phone_number

                # Update contact
                contact_update = ContactUpdate(**update_data)
                contact = contact_service.update_contact(db, contact.id, contact_update, company_id)
                updated = True
                print(f"[CREATE/UPDATE CONTACT TOOL] Updated existing contact ID: {contact.id}")
                print(f"[CREATE/UPDATE CONTACT TOOL] Updated contact data - Name: {contact.name}, Email: {contact.email}, Phone: {contact.phone_number}")

        if not contact:
            # Create new contact
            contact_data = ContactCreate(
                name=name,
                email=email,
                phone_number=phone_number,
                custom_attributes={},
                company_id=company_id
            )
            contact = contact_service.create_contact(db, contact_data, company_id)

            # Link contact to session
            session_update = ConversationSessionUpdate(contact_id=contact.id)
            conversation_session_service.update_session(db, session_id, session_update)
            print(f"[CREATE/UPDATE CONTACT TOOL] Created new contact ID: {contact.id} and linked to session")

        # Broadcast contact update to frontend via WebSocket
        try:
            from app.services.connection_manager import manager
            import json

            contact_update_message = json.dumps({
                "type": "contact_updated",
                "session_id": session_id,
                "contact": {
                    "id": contact.id,
                    "name": contact.name,
                    "email": contact.email,
                    "phone_number": contact.phone_number
                },
                "action": "updated" if updated else "created"
            })
            await manager.broadcast_to_company(company_id, contact_update_message)
            print(f"[CREATE/UPDATE CONTACT TOOL] Broadcasted contact update to company {company_id}")
        except Exception as broadcast_error:
            print(f"[CREATE/UPDATE CONTACT TOOL] Warning: Failed to broadcast contact update: {broadcast_error}")
            # Don't fail the tool if broadcast fails

        # Determine what's still missing and provide formatted response
        has_name = contact.name and contact.name.strip()
        has_email = contact.email and contact.email.strip()
        has_phone = contact.phone_number and contact.phone_number.strip()

        if not has_name:
            formatted_msg = "To get started, may I have your name?"
        elif not has_email:
            formatted_msg = "Great! And what's your email address?"
        elif not has_phone:
            formatted_msg = "Perfect! Lastly, what's your phone number?"
        else:
            # All fields present - thank them and ask how to help
            formatted_msg = f"Thank you, {contact.name}! How can I help you today?"

        return {
            "result": {
                "status": "success",
                "action": "updated" if updated else "created",
                "contact": {
                    "id": contact.id,
                    "name": contact.name,
                    "email": contact.email,
                    "phone_number": contact.phone_number
                }
            },
            "formatted_response": formatted_msg
        }

    except Exception as e:
        print(f"[CREATE/UPDATE CONTACT TOOL] Error: {e}")
        return {
            "error": "An error occurred while creating/updating contact.",
            "details": str(e),
            "traceback": traceback.format_exc()
        }


async def execute_get_contact_info_tool(db: Session, session_id: str, company_id: int):
    """
    Executes the built-in get_contact_info tool.
    Retrieves the contact information for the current conversation.

    Args:
        db: Database session
        session_id: Conversation session ID
        company_id: Company ID

    Returns:
        Dictionary with contact information or null if no contact exists
    """
    from app.services import contact_service

    print(f"[GET CONTACT INFO TOOL] Session: {session_id}")

    try:
        # Get the session
        session = conversation_session_service.get_session_by_conversation_id(db, session_id, company_id)
        if not session:
            return {"error": "Session not found"}

        # Check if session has a contact
        if not session.contact_id:
            print(f"[GET CONTACT INFO TOOL] No contact linked to session")
            return {
                "result": {
                    "status": "success",
                    "contact": None,
                    "message": "No contact information available for this conversation"
                },
                "formatted_response": "To get started, may I have your name?"
            }

        # Get the contact
        contact = contact_service.get_contact(db, session.contact_id, company_id)
        if not contact:
            return {"error": "Contact not found"}

        print(f"[GET CONTACT INFO TOOL] Found contact ID: {contact.id}")
        print(f"[GET CONTACT INFO TOOL] Contact data - Name: {contact.name}, Email: {contact.email}, Phone: {contact.phone_number}")

        # Determine what's missing and provide formatted response
        has_name = contact.name and contact.name.strip()
        has_email = contact.email and contact.email.strip()
        has_phone = contact.phone_number and contact.phone_number.strip()

        if not has_name:
            formatted_msg = "To get started, may I have your name?"
        elif not has_email:
            formatted_msg = "Great! And what's your email address?"
        elif not has_phone:
            formatted_msg = "Perfect! Lastly, what's your phone number?"
        else:
            # All fields present
            formatted_msg = f"Hello, {contact.name}! How can I help you today?"

        return {
            "result": {
                "status": "success",
                "contact": {
                    "id": contact.id,
                    "name": contact.name,
                    "email": contact.email,
                    "phone_number": contact.phone_number
                }
            },
            "formatted_response": formatted_msg
        }

    except Exception as e:
        print(f"[GET CONTACT INFO TOOL] Error: {e}")
        return {
            "error": "An error occurred while retrieving contact information.",
            "details": str(e),
            "traceback": traceback.format_exc()
        }
