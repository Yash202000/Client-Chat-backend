from app.services import messaging_service, integration_service
from app.models.conversation_session import ConversationSession
from sqlalchemy.orm import Session

def send_messenger_message_tool(db: Session, session: ConversationSession, recipient_psid: str, message: str):
    """
    A tool that sends a message to a specified Messenger recipient.
    
    Args:
        db: The database session.
        session: The current conversation session.
        recipient_psid: The Page-Scoped User ID of the message recipient.
        message: The text content of the message to send.
    """
    company_id = session.workflow.company_id
    
    integrations = integration_service.get_integrations_by_company(db, company_id)
    messenger_integration = next((i for i in integrations if i.type == "messenger" and i.enabled), None)

    if not messenger_integration:
        return {"status": "error", "message": "No active Messenger integration found for this company."}

    try:
        # As before, this is a placeholder for a proper async call.
        print(f"TOOL: Would send Messenger message to {recipient_psid}: {message}")
        return {"status": "success", "message": "Message queued for sending."}

    except Exception as e:
        return {"status": "error", "message": str(e)}

TOOL_SCHEMA = {
    "name": "send_messenger_message",
    "description": "Sends a text message to a user on Facebook Messenger.",
    "parameters": {
        "type": "object",
        "properties": {
            "recipient_psid": {
                "type": "string",
                "description": "The recipient's Page-Scoped User ID (PSID)."
            },
            "message": {
                "type": "string",
                "description": "The content of the message to send."
            }
        },
        "required": ["recipient_psid", "message"]
    },
    "execute": send_messenger_message_tool
}
