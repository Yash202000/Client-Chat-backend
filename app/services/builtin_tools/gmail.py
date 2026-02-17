import traceback
import base64
import json
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any
from sqlalchemy.orm import Session
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build, Resource

from app.services import integration_service
from app.core.config import settings


def get_gmail_client(db: Session, integration) -> Resource:
    """
    Creates and returns an authenticated Gmail API client.
    Handles token refresh and updates the integration if a new token is issued.
    """
    credentials = integration_service.get_decrypted_credentials(integration)
    
    print(f"[GMAIL CLIENT] Credentials keys: {list(credentials.keys())}")
    print(f"[GMAIL CLIENT] token present: {'token' in credentials}")
    print(f"[GMAIL CLIENT] refresh_token present: {'refresh_token' in credentials}")
    
    # Note: google.py callback stores 'token' but older code stored 'access_token'
    access_token = credentials.get("token") or credentials.get("access_token")
    refresh_token = credentials.get("refresh_token")
    
    print(f"[GMAIL CLIENT] Using access_token: {bool(access_token)}")
    print(f"[GMAIL CLIENT] Using refresh_token: {bool(refresh_token)}")
    
    # Parse expiry if stored
    expiry_str = credentials.get("expiry")
    expiry = datetime.fromisoformat(expiry_str) if expiry_str else None

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        expiry=expiry,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/gmail.modify"]
    )

    if not creds.valid and creds.refresh_token:
        try:
            creds.refresh(Request())
            new_credentials = {
                "user_email": credentials.get("user_email"),
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "expiry": creds.expiry.isoformat() if creds.expiry else None,
            }
            integration.credentials = integration_service.vault_service.encrypt(json.dumps(new_credentials))
            db.commit()
            db.refresh(integration)
        except RefreshError as e:
            raise Exception(f"Failed to refresh Gmail token: {e}")

    return build('gmail', 'v1', credentials=creds)


async def execute_send_email_tool(db: Session, session_id: str, company_id: int, parameters: dict):
    """
    Sends an email via Gmail API.
    
    Args:
        db: Database session
        session_id: Conversation session ID
        company_id: Company ID
        parameters: Tool parameters (to_email, subject, body, cc, bcc)
    
    Returns:
        Dictionary with send result
    """
    to_email = parameters.get("to_email")
    subject = parameters.get("subject", "")
    body = parameters.get("body", "")
    cc = parameters.get("cc")
    bcc = parameters.get("bcc")
    
    print(f"[GMAIL TOOL] Sending email to: {to_email}")
    print(f"[GMAIL TOOL] Subject: {subject}")
    print(f"[GMAIL TOOL] Session: {session_id}, Company: {company_id}")
    
    if not to_email:
        return {"error": "to_email is required"}
    
    if not subject and not body:
        return {"error": "Either subject or body is required"}
    
    try:
        # Get Gmail integration for the company
        integration = integration_service.get_integration_by_type_and_company(
            db, 
            integration_type='gmail', 
            company_id=company_id
        )
        
        if not integration:
            return {
                "error": "Gmail is not connected. Please connect your Google account first.",
                "status": "not_connected"
            }
        
        print(f"[GMAIL TOOL] Found integration: type={integration.type}, id={integration.id}")
        
        # Get Gmail client
        client = get_gmail_client(db, integration)

        # Build MIME message
        message = MIMEMultipart()
        message["to"] = to_email
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc
        message["subject"] = subject
        message.attach(MIMEText(body, "plain"))
        
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        sent_message = client.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()
        
        print(f"[GMAIL TOOL] Email sent successfully: {sent_message.get('id')}")
        
        return {
            "result": {
                "status": "success",
                "message_id": sent_message.get('id'),
                "thread_id": sent_message.get('threadId'),
                "to": to_email,
                "subject": subject
            },
            "formatted_response": f"Email sent successfully to {to_email} with subject '{subject}'."
        }
        
    except Exception as e:
        print(f"[GMAIL TOOL] Error sending email: {e}")
        print(traceback.format_exc())
        return {
            "error": f"Failed to send email: {str(e)}",
            "traceback": traceback.format_exc()
        }


async def execute_read_emails_tool(db: Session, session_id: str, company_id: int, parameters: dict):
    """
    Reads emails from Gmail inbox.
    
    Args:
        db: Database session
        session_id: Conversation session ID
        company_id: Company ID
        parameters: Tool parameters (max_results, query, unread_only)
    
    Returns:
        Dictionary with email list
    """
    max_results = int(parameters.get("max_results", 10))
    max_results = max(max_results, 1)
    max_results = min(max_results, 50)
    query = parameters.get("query", "")
    unread_only = parameters.get("unread_only", False)
    
    print(f"[GMAIL TOOL] Reading emails, max_results: {max_results}")
    print(f"[GMAIL TOOL] Query: {query}, Unread only: {unread_only}")
    print(f"[GMAIL TOOL] Session: {session_id}, Company: {company_id}")
    
    try:
        # Get Gmail integration for the company
        integration = integration_service.get_integration_by_type_and_company(
            db, 
            integration_type='gmail', 
            company_id=company_id
        )
        
        if not integration:
            return {
                "error": "Gmail is not connected. Please connect your Google account first.",
                "status": "not_connected"
            }
        
        # Get Gmail client
        client = get_gmail_client(db, integration)
        
        # Build search query
        search_query = query
        if unread_only:
            search_query = f"is:unread {search_query}".strip()
        
        # List messages
        results = client.users().messages().list(
            userId='me',
            q=search_query,
            maxResults=max_results
        ).execute()
        
        messages = results.get('messages', [])
        
        if not messages:
            return {
                "result": {
                    "status": "success",
                    "emails": [],
                    "total_count": 0,
                    "message": "No emails found matching your criteria."
                }
            }
        
        # Fetch details for each message
        email_list = []
        for msg in messages:
            msg_data = client.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata',
                metadataHeaders=['From', 'To', 'Subject', 'Date']
            ).execute()
            
            headers = {h['name']: h['value'] for h in msg_data.get('payload', {}).get('headers', [])}
            
            email_list.append({
                "id": msg['id'],
                "thread_id": msg['threadId'],
                "from": headers.get('From', ''),
                "to": headers.get('To', ''),
                "subject": headers.get('Subject', '(No Subject)'),
                "date": headers.get('Date', ''),
                "snippet": msg_data.get('snippet', ''),
                "is_unread": 'UNREAD' in msg_data.get('labelIds', [])
            })
        
        print(f"[GMAIL TOOL] Found {len(email_list)} emails")
        
        return {
            "result": {
                "status": "success",
                "emails": email_list,
                "total_count": len(email_list)
            }
        }
        
    except Exception as e:
        print(f"[GMAIL TOOL] Error reading emails: {e}")
        print(traceback.format_exc())
        return {
            "error": f"Failed to read emails: {str(e)}",
            "traceback": traceback.format_exc()
        }


async def execute_get_email_content_tool(db: Session, session_id: str, company_id: int, parameters: dict):
    """
    Gets the full content of a specific email.
    
    Args:
        db: Database session
        session_id: Conversation session ID
        company_id: Company ID
        parameters: Tool parameters (email_id)
    
    Returns:
        Dictionary with email content
    """
    email_id = parameters.get("email_id")
    
    print(f"[GMAIL TOOL] Getting email content for: {email_id}")
    print(f"[GMAIL TOOL] Session: {session_id}, Company: {company_id}")
    
    if not email_id:
        return {"error": "email_id is required"}
    
    try:
        # Get Gmail integration for the company
        integration = integration_service.get_integration_by_type_and_company(
            db, 
            integration_type='gmail', 
            company_id=company_id
        )
        
        if not integration:
            return {
                "error": "Gmail is not connected. Please connect your Google account first.",
                "status": "not_connected"
            }
        
        # Get Gmail client
        client = get_gmail_client(db, integration)
        
        # Get full message
        msg_data = client.users().messages().get(
            userId='me',
            id=email_id,
            format='full'
        ).execute()
        
        headers = {h['name']: h['value'] for h in msg_data.get('payload', {}).get('headers', [])}
        
        # Extract body content
        body = ""
        payload = msg_data.get('payload', {})
        
        if 'body' in payload and payload['body'].get('data'):
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
        elif 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain' and part['body'].get('data'):
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    break
                elif part['mimeType'] == 'text/html' and part['body'].get('data') and not body:
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
        
        print(f"[GMAIL TOOL] Retrieved email content, body length: {len(body)}")
        
        return {
            "result": {
                "status": "success",
                "email": {
                    "id": email_id,
                    "thread_id": msg_data.get('threadId'),
                    "from": headers.get('From', ''),
                    "to": headers.get('To', ''),
                    "cc": headers.get('Cc', ''),
                    "subject": headers.get('Subject', '(No Subject)'),
                    "date": headers.get('Date', ''),
                    "body": body,
                    "snippet": msg_data.get('snippet', ''),
                    "is_unread": 'UNREAD' in msg_data.get('labelIds', []),
                    "labels": msg_data.get('labelIds', [])
                }
            }
        }
        
    except Exception as e:
        print(f"[GMAIL TOOL] Error getting email content: {e}")
        print(traceback.format_exc())
        return {
            "error": f"Failed to get email content: {str(e)}",
            "traceback": traceback.format_exc()
        }
