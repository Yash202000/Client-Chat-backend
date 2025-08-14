from sqlalchemy.orm import Session
from app.services import integration_service
from app.models.integration import Integration
from typing import Dict, Any, List
import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build, Resource
from app.core.config import settings
import os

def get_google_calendar_client(db: Session, integration: Integration) -> Resource:
    """
    Creates and returns an authenticated Google Calendar API client.
    Handles token refresh and updates the integration if a new token is issued.
    """
    credentials = integration_service.get_decrypted_credentials(integration)
    
    creds = Credentials(
        token=credentials.get("access_token"),
        refresh_token=credentials.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GMAIL_CLIENT_ID,
        client_secret=settings.GMAIL_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/calendar"]
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # If refresh was successful, update the stored credentials
            new_credentials = {
                "user_email": credentials.get("user_email"),
                "access_token": creds.token,
                "refresh_token": creds.refresh_token,
            }
            integration.credentials = integration_service.vault_service.encrypt(str(new_credentials))
            db.commit()
            db.refresh(integration)
        except RefreshError as e:
            # Handle the case where the refresh token is invalid
            # This might require re-authentication by the user
            raise Exception(f"Failed to refresh Google token: {e}")

    return build('calendar', 'v3', credentials=creds)


def get_available_slots(db: Session, integration_id: int, start_time: datetime, end_time: datetime, duration_minutes: int) -> List[Dict[str, Any]]:
    """
    Finds available time slots in a Google Calendar within a given range for a specific duration.
    """
    integration = integration_service.get_integration(db, integration_id=integration_id, company_id=1) # Assuming company_id=1 for now
    if not integration or integration.type != "google_calendar":
        raise ValueError("Invalid Google Calendar integration.")

    client = get_google_calendar_client(db, integration)
    
    freebusy_query = {
        "timeMin": start_time.isoformat(),
        "timeMax": end_time.isoformat(),
        "items": [{"id": "primary"}]
    }
    
    freebusy_result = client.freebusy().query(body=freebusy_query).execute()
    busy_slots = freebusy_result.get('calendars', {}).get('primary', {}).get('busy', [])

    # Create a list of all potential start times
    potential_slots = []
    current_time = start_time
    while current_time + datetime.timedelta(minutes=duration_minutes) <= end_time:
        potential_slots.append(current_time)
        current_time += datetime.timedelta(minutes=15) # Check every 15 minutes

    available_slots = []
    for slot_start in potential_slots:
        slot_end = slot_start + datetime.timedelta(minutes=duration_minutes)
        is_busy = False
        for busy_slot in busy_slots:
            busy_start = datetime.datetime.fromisoformat(busy_slot['start'])
            busy_end = datetime.datetime.fromisoformat(busy_slot['end'])
            if max(slot_start, busy_start) < min(slot_end, busy_end):
                is_busy = True
                break
        if not is_busy:
            available_slots.append({
                "start": slot_start.isoformat(),
                "end": slot_end.isoformat()
            })
            
    return available_slots

def create_event(db: Session, integration_id: int, title: str, start_time: datetime, end_time: datetime, attendees: List[str]) -> Dict[str, Any]:
    """
    Creates an event in a Google Calendar.
    """
    integration = integration_service.get_integration(db, integration_id=integration_id, company_id=1) # Assuming company_id=1 for now
    if not integration or integration.type != "google_calendar":
        raise ValueError("Invalid Google Calendar integration.")

    client = get_google_calendar_client(db, integration)

    event = {
        'summary': title,
        'start': {
            'dateTime': start_time.isoformat(),
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': end_time.isoformat(),
            'timeZone': 'UTC',
        },
        'attendees': [{'email': email} for email in attendees],
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'email', 'minutes': 24 * 60},
                {'method': 'popup', 'minutes': 10},
            ],
        },
    }

    created_event = client.events().insert(calendarId='primary', body=event).execute()
    return created_event