"""
Contact builtin tools implementation.
Handles creating, updating, and retrieving contact information.
"""
import traceback
from sqlalchemy.orm import Session
from app.models.tool import Tool
from app.services import conversation_session_service, contact_service, tool_followup_service
from app.schemas.contact import ContactCreate, ContactUpdate
from app.schemas.conversation_session import ConversationSessionUpdate


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
            # Check if contact already exists with same phone_number or email (deduplication)
            from app.models.contact import Contact
            existing_contact = None

            if phone_number:
                existing_contact = db.query(Contact).filter(
                    Contact.company_id == company_id,
                    Contact.phone_number == phone_number
                ).first()
                if existing_contact:
                    print(f"[CREATE/UPDATE CONTACT TOOL] Found existing contact by phone_number: {existing_contact.id}")

            if not existing_contact and email:
                existing_contact = db.query(Contact).filter(
                    Contact.company_id == company_id,
                    Contact.email == email
                ).first()
                if existing_contact:
                    print(f"[CREATE/UPDATE CONTACT TOOL] Found existing contact by email: {existing_contact.id}")

            if existing_contact:
                # Use existing contact and update missing fields
                contact = existing_contact
                needs_update = False

                if name and not contact.name:
                    contact.name = name
                    needs_update = True
                if email and not contact.email:
                    contact.email = email
                    needs_update = True
                if phone_number and not contact.phone_number:
                    contact.phone_number = phone_number
                    needs_update = True

                if needs_update:
                    db.commit()
                    db.refresh(contact)
                    updated = True
                    print(f"[CREATE/UPDATE CONTACT TOOL] Updated existing contact ID: {contact.id} with missing fields")
                else:
                    print(f"[CREATE/UPDATE CONTACT TOOL] Linked session to existing contact ID: {contact.id}")
            else:
                # Create new contact
                contact_data = ContactCreate(
                    name=name,
                    email=email,
                    phone_number=phone_number,
                    custom_attributes={},
                    company_id=company_id
                )
                contact = contact_service.create_contact(db, contact_data, company_id)
                print(f"[CREATE/UPDATE CONTACT TOOL] Created new contact ID: {contact.id}")

            # Link contact to session
            session_update = ConversationSessionUpdate(contact_id=contact.id)
            conversation_session_service.update_session(db, session_id, session_update)
            print(f"[CREATE/UPDATE CONTACT TOOL] Linked contact {contact.id} to session")

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

        # Get follow-up response from builtin tool's follow_up_config
        builtin_tool = db.query(Tool).filter(
            Tool.name == "create_or_update_contact",
            Tool.tool_type == "builtin"
        ).first()

        formatted_msg = None
        if builtin_tool and builtin_tool.follow_up_config:
            # Pass current contact values as provided_params
            provided_params = {
                "name": contact.name if contact else None,
                "email": contact.email if contact else None,
                "phone_number": contact.phone_number if contact else None
            }
            formatted_msg = tool_followup_service.build_follow_up_response(
                db=db,
                tool=builtin_tool,
                provided_params=provided_params,
                session_id=session_id,
                company_id=company_id
            )

        result = {
            "result": {
                "status": "success",
                "action": "updated" if updated else "created",
                "contact": {
                    "id": contact.id,
                    "name": contact.name,
                    "email": contact.email,
                    "phone_number": contact.phone_number
                }
            }
        }
        if formatted_msg:
            result["formatted_response"] = formatted_msg

        return result

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
    print(f"\n{'='*60}")
    print(f"[GET CONTACT INFO TOOL] === STARTING ===")
    print(f"[GET CONTACT INFO TOOL] Session ID: {session_id}")
    print(f"[GET CONTACT INFO TOOL] Company ID: {company_id}")

    try:
        # Get the session
        session = conversation_session_service.get_session_by_conversation_id(db, session_id, company_id)
        if not session:
            print(f"[GET CONTACT INFO TOOL] ERROR: Session not found!")
            return {"error": "Session not found"}

        print(f"[GET CONTACT INFO TOOL] Session found - contact_id: {session.contact_id}")

        # Get the builtin tool for follow_up_config
        builtin_tool = db.query(Tool).filter(
            Tool.name == "get_contact_info",
            Tool.tool_type == "builtin"
        ).first()
        print(f"[GET CONTACT INFO TOOL] Builtin tool found: {builtin_tool is not None}")
        print(f"[GET CONTACT INFO TOOL] Follow-up config enabled: {builtin_tool.follow_up_config.get('enabled') if builtin_tool and builtin_tool.follow_up_config else False}")

        # Check if session has a contact
        if not session.contact_id:
            print(f"[GET CONTACT INFO TOOL] ⚠️  NO CONTACT LINKED TO SESSION!")
            # Get follow-up response for no contact case
            formatted_msg = None
            if builtin_tool and builtin_tool.follow_up_config:
                formatted_msg = tool_followup_service.build_follow_up_response(
                    db=db,
                    tool=builtin_tool,
                    provided_params={},  # No contact data yet
                    session_id=session_id,
                    company_id=company_id
                )
            result = {
                "result": {
                    "status": "success",
                    "contact": None,
                    "message": "No contact information available for this conversation"
                }
            }
            if formatted_msg:
                result["formatted_response"] = formatted_msg
            return result

        # Get the contact
        contact = contact_service.get_contact(db, session.contact_id, company_id)
        if not contact:
            print(f"[GET CONTACT INFO TOOL] ERROR: Contact ID {session.contact_id} not found in database!")
            return {"error": "Contact not found"}

        print(f"[GET CONTACT INFO TOOL] ✓ Contact found!")
        print(f"[GET CONTACT INFO TOOL]   - ID: {contact.id}")
        print(f"[GET CONTACT INFO TOOL]   - Name: '{contact.name}' (empty: {not contact.name})")
        print(f"[GET CONTACT INFO TOOL]   - Email: '{contact.email}' (empty: {not contact.email})")
        print(f"[GET CONTACT INFO TOOL]   - Phone: '{contact.phone_number}' (empty: {not contact.phone_number})")

        # Get follow-up response from builtin tool's follow_up_config
        formatted_msg = None
        if builtin_tool and builtin_tool.follow_up_config:
            provided_params = {
                "name": contact.name if contact else None,
                "email": contact.email if contact else None,
                "phone_number": contact.phone_number if contact else None
            }
            formatted_msg = tool_followup_service.build_follow_up_response(
                db=db,
                tool=builtin_tool,
                provided_params=provided_params,
                session_id=session_id,
                company_id=company_id
            )

        result = {
            "result": {
                "status": "success",
                "contact": {
                    "id": contact.id,
                    "name": contact.name,
                    "email": contact.email,
                    "phone_number": contact.phone_number
                }
            }
        }
        if formatted_msg:
            result["formatted_response"] = formatted_msg

        return result

    except Exception as e:
        print(f"[GET CONTACT INFO TOOL] Error: {e}")
        return {
            "error": "An error occurred while retrieving contact information.",
            "details": str(e),
            "traceback": traceback.format_exc()
        }
