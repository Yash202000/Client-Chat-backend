import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Any
from sqlalchemy.orm import Session
from app.models.tool import Tool
from app.services import integration_service
from app.services.calendar_service import get_google_calendar_client


async def execute_check_calendar_availability_tool( db: Session, session_id: str, company_id: int, parameters: dict ):
    """
    Checks calendar availability for the next 7 days.
    Returns available 15-minute slots between 9 AM and 6 PM.
    
    Args:
        db: Database session
        session_id: Conversation session ID
        company_id: Company ID
        parameters: Tool parameters (optional: days)
    
    Returns:
        Dictionary with available and occupied slots
    """
    # Convert to int - parameters may come as strings from workflow
    days = int(parameters.get("days", 7))
    
    # Working hours: 9 AM to 6 PM
    work_start_hour = 9
    work_end_hour = 18
    
    print(f"[CALENDAR TOOL] Checking availability for next {days} days")
    print(f"[CALENDAR TOOL] Session: {session_id}, Company: {company_id}")
    
    try:
        # Get Google Calendar integration for the company
        integration = integration_service.get_integration_by_type_and_company(
            db, 
            integration_type='google_calendar', 
            company_id=company_id
        )
        
        if not integration:
            return {
                "error": "Google Calendar is not connected. Please connect your Google account first.",
                "status": "not_connected"
            }
        
        # Debug: print integration details
        print(f"[CALENDAR TOOL] Found integration: type={integration.type}, id={integration.id}")
        print(f"[CALENDAR TOOL] Raw credentials (encrypted): {integration.credentials[:50] if integration.credentials else 'NONE'}...")
        
        # Get calendar client
        client = get_google_calendar_client(db, integration)
        
        # Calculate time range (use timezone-aware datetime)
        from datetime import timezone
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days)).isoformat()
        
        # Fetch busy times from Google Calendar
        freebusy_query = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": "primary"}]
        }
        
        freebusy_result = client.freebusy().query(body=freebusy_query).execute()
        busy_slots = freebusy_result.get('calendars', {}).get('primary', {}).get('busy', [])
        
        print(f"[CALENDAR TOOL] Found {len(busy_slots)} busy slots from Google Calendar")
        
        # Convert busy slots to datetime objects
        busy_periods = []
        for slot in busy_slots:
            busy_start = datetime.fromisoformat(slot['start'].replace('Z', '+00:00'))
            busy_end = datetime.fromisoformat(slot['end'].replace('Z', '+00:00'))
            busy_periods.append((busy_start, busy_end))
        
        # Sort busy periods by start time
        busy_periods.sort(key=lambda x: x[0])
        
        # Generate available (free) time ranges by finding gaps between busy periods
        available_ranges = []
        occupied_ranges = []
        
        current_day = now.date()
        for day_offset in range(days):
            check_date = current_day + timedelta(days=day_offset)
            
            # Define working hours for this day
            day_start = datetime(
                check_date.year, check_date.month, check_date.day,
                work_start_hour, 0, tzinfo=timezone.utc
            )
            day_end = datetime(
                check_date.year, check_date.month, check_date.day,
                work_end_hour, 0, tzinfo=timezone.utc
            )
            
            # Skip if day is in the past
            if day_end < now:
                continue
            
            # Adjust day_start if it's in the past (for today)
            if day_start < now:
                # Round up to next 15-min slot
                minutes = now.minute
                rounded_minutes = ((minutes // 15) + 1) * 15
                if rounded_minutes >= 60:
                    day_start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                else:
                    day_start = now.replace(minute=rounded_minutes, second=0, microsecond=0)
            
            # Get busy periods for this day only
            day_busy = []
            for busy_start, busy_end in busy_periods:
                # Check if this busy period overlaps with this day's working hours
                if busy_end > day_start and busy_start < day_end:
                    # Clip to working hours
                    overlap_start = max(busy_start, day_start)
                    overlap_end = min(busy_end, day_end)
                    day_busy.append((overlap_start, overlap_end))
                    
                    # Add to occupied ranges
                    occupied_ranges.append({
                        "date": check_date.isoformat(),
                        "day_name": check_date.strftime("%A"),
                        "start_time": overlap_start.strftime("%H:%M"),
                        "end_time": overlap_end.strftime("%H:%M"),
                        "start_datetime": overlap_start.isoformat(),
                        "end_datetime": overlap_end.isoformat()
                    })
            
            # Calculate free ranges (gaps between busy periods)
            free_start = day_start
            for busy_start, busy_end in sorted(day_busy, key=lambda x: x[0]):
                if busy_start > free_start:
                    # There's a free gap before this busy period
                    available_ranges.append({
                        "date": check_date.isoformat(),
                        "day_name": check_date.strftime("%A"),
                        "start_time": free_start.strftime("%H:%M"),
                        "end_time": busy_start.strftime("%H:%M"),
                        "start_datetime": free_start.isoformat(),
                        "end_datetime": busy_start.isoformat(),
                        "duration_minutes": int((busy_start - free_start).total_seconds() / 60)
                    })
                free_start = max(free_start, busy_end)
            
            # Add remaining free time after last busy period
            if free_start < day_end:
                available_ranges.append({
                    "date": check_date.isoformat(),
                    "day_name": check_date.strftime("%A"),
                    "start_time": free_start.strftime("%H:%M"),
                    "end_time": day_end.strftime("%H:%M"),
                    "start_datetime": free_start.isoformat(),
                    "end_datetime": day_end.isoformat(),
                    "duration_minutes": int((day_end - free_start).total_seconds() / 60)
                })
        
        print(f"[CALENDAR TOOL] Found {len(available_ranges)} available time ranges, {len(occupied_ranges)} occupied ranges")
        
        return {
            "result": {
                "status": "success",
                "days_checked": days,
                "working_hours": f"{work_start_hour}:00 - {work_end_hour}:00",
                "available_ranges": available_ranges,
                "occupied_ranges": occupied_ranges,
                "total_available_ranges": len(available_ranges),
                "total_occupied_ranges": len(occupied_ranges)
            }
        }
        
    except Exception as e:
        print(f"[CALENDAR TOOL] Error checking availability: {e}")
        print(traceback.format_exc())
        return {
            "error": f"Failed to check calendar availability: {str(e)}",
            "traceback": traceback.format_exc()
        }


async def execute_schedule_calendar_event_tool(db: Session, session_id: str, company_id: int, parameters: dict):
    """
    Schedules a calendar event at the specified time.
    
    Args:
        db: Database session
        session_id: Conversation session ID
        company_id: Company ID
        parameters: Tool parameters (start_time, end_time, title, attendee_email, description)
    
    Returns:
        Dictionary with event creation result
    """
    start_time = parameters.get("start_time")
    end_time = parameters.get("end_time")
    title = parameters.get("title", "Scheduled Appointment")
    attendee_email = parameters.get("attendee_email")
    description = parameters.get("description", "")
    
    print(f"[CALENDAR TOOL] Scheduling event: {title}")
    print(f"[CALENDAR TOOL] Time: {start_time} to {end_time}")
    print(f"[CALENDAR TOOL] Attendee: {attendee_email}")
    
    if not start_time or not end_time:
        return {"error": "start_time and end_time are required"}
    
    if not attendee_email:
        return {"error": "attendee_email is required"}
    
    try:
        # Get Google Calendar integration
        integration = integration_service.get_integration_by_type_and_company(
            db, 
            integration_type='google_calendar', 
            company_id=company_id
        )
        
        if not integration:
            integration = integration_service.get_integration_by_type_and_company(
                db, 
                integration_type='gmail', 
                company_id=company_id
            )
        
        if not integration:
            return {
                "error": "Google Calendar is not connected. Please connect your Google account first.",
                "status": "not_connected"
            }
        
        # Get calendar client
        client = get_google_calendar_client(db, integration)
        
        # Parse datetime strings
        if isinstance(start_time, str):
            start_dt = datetime.fromisoformat(start_time.replace('Z', ''))
        else:
            start_dt = start_time
            
        if isinstance(end_time, str):
            end_dt = datetime.fromisoformat(end_time.replace('Z', ''))
        else:
            end_dt = end_time
        
        # Create event
        event = {
            'summary': title,
            'description': description,
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': 'UTC',
            },
            'attendees': [
                {'email': attendee_email}
            ],
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 30},
                ],
            },
        }
        
        created_event = client.events().insert(
            calendarId='primary', 
            body=event,
            sendUpdates='all'  # Notify attendees
        ).execute()
        
        print(f"[CALENDAR TOOL] Event created: {created_event.get('id')}")
        print(f"[CALENDAR TOOL] Event link: {created_event.get('htmlLink')}")
        
        return {
            "result": {
                "status": "success",
                "message": f"Appointment scheduled successfully for {start_dt.strftime('%A, %B %d at %I:%M %p')}",
                "event": {
                    "id": created_event.get('id'),
                    "title": title,
                    "start_time": start_dt.isoformat(),
                    "end_time": end_dt.isoformat(),
                    "attendee": attendee_email,
                    "link": created_event.get('htmlLink')
                }
            },
            "formatted_response": f"I've scheduled your appointment for {start_dt.strftime('%A, %B %d at %I:%M %p')}. A calendar invite has been sent to {attendee_email}."
        }
        
    except Exception as e:
        print(f"[CALENDAR TOOL] Error scheduling event: {e}")
        print(traceback.format_exc())
        return {
            "error": f"Failed to schedule event: {str(e)}",
            "traceback": traceback.format_exc()
        }
