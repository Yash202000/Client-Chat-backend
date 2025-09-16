import os
import sys
import json

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.schemas.tool import ToolCreate
from app.services import tool_service

def setup_schedule_appointment_tool():
    """
    Creates the 'Schedule Appointment' tool in the database.
    """
    db = SessionLocal()
    try:
        company_id = 1  # Assuming a default company_id for setup

        tool_name = "Schedule Appointment"
        tool_description = "Schedules an appointment in a Google Calendar. It finds the next available slot and books it."
        
        tool_code = """
from app.services import calendar_service
from app.services import integration_service
import datetime

def run(params: dict, config: dict):
    db = config.get("db")
    company_id = config.get("company_id")
    attendee_email = params.get("attendee_email")
    duration_minutes = params.get("duration_minutes")
    appointment_title = params.get("appointment_title")

    # Find the Google Calendar integration for the company
    integration = integration_service.get_integration_by_type_and_company(db, "google_calendar", company_id)
    if not integration:
        return {"error": "Google Calendar integration not found for this company."}

    # Find available slots (e.g., search in the next 7 days)
    now = datetime.datetime.now(datetime.UTC)
    start_time = now
    end_time = now + datetime.timedelta(days=7)
    
    available_slots = calendar_service.get_available_slots(db, integration.id, start_time, end_time, duration_minutes)
    
    if not available_slots:
        return {"error": "No available slots found in the next 7 days."}
        
    # Book the first available slot
    slot_to_book = available_slots[0]
    event_start_time = datetime.datetime.fromisoformat(slot_to_book['start'])
    event_end_time = datetime.datetime.fromisoformat(slot_to_book['end'])
    
    # The user who owns the calendar is the organizer
    organizer_email = integration_service.get_decrypted_credentials(integration).get("user_email")
    attendees = [attendee_email, organizer_email]
    
    created_event = calendar_service.create_event(
        db,
        integration.id,
        appointment_title,
        event_start_time,
        event_end_time,
        attendees
    )
    
    return {
        "success": True,
        "event_summary": created_event.get('summary'),
        "event_link": created_event.get('htmlLink')
    }
"""

        parameter_schema = {
            "type": "object",
            "properties": {
                "attendee_email": {
                    "type": "string",
                    "title": "Attendee Email",
                    "description": "The email address of the person to invite to the appointment."
                },
                "duration_minutes": {
                    "type": "integer",
                    "title": "Duration (minutes)",
                    "description": "The duration of the appointment in minutes.",
                    "default": 30
                },
                "appointment_title": {
                    "type": "string",
                    "title": "Appointment Title",
                    "description": "The title or summary for the calendar event."
                }
            },
            "required": ["attendee_email", "duration_minutes", "appointment_title"]
        }

        tool_create = ToolCreate(
            name=tool_name,
            description=tool_description,
            parameters=parameter_schema,
            code=tool_code,
            tool_type="custom"
        )

        db_tool = tool_service.get_tool_by_name(db=db, name=tool_name, company_id=company_id)
        if db_tool:
            print(f"Tool '{tool_name}' already exists.")
        else:
            tool_service.create_tool(db=db, tool=tool_create, company_id=company_id)
            print(f"Successfully created the '{tool_name}' tool.")

    finally:
        db.close()

if __name__ == "__main__":
    setup_schedule_appointment_tool()
