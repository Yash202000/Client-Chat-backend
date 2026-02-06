from fastmcp import FastMCP
from pydantic import BaseModel
from typing import Literal, Optional
import os
import sys
import json

# Ensure the mcp folder is in path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automax import Automax3

mcp = FastMCP(name="Automax Incident MCP Server")

# login once at startup
auto = Automax3()
auto.login()
 

class IncidentCreate(BaseModel):
    caller_name: str
    classification: str
    location: str
    
    # Data from frontend (small data sent via LiveKit data channel)
    attachment_id: Optional[str] = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
 
    # defaults (user can override)
    channel: str = "Chatbot"
    national_id: str = "45"
    criticality: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
 
 
@mcp.tool()
def create_incident(incident: IncidentCreate):
    """
    Create an incident with all collected information.
    
    Args:
        caller_name: Name of the person reporting (from voice)
        classification: Classification ID (from voice + lookup)
        location: Location ID (from voice + lookup)
        attachment_id: Attachment ID from frontend form (image upload)
        latitude: GPS latitude from frontend
        longitude: GPS longitude from frontend
    """
    # Format coordinates for the API
    coordinates = ""
    if incident.latitude and incident.longitude:
        coordinates = json.dumps({"coordinates": [incident.latitude, incident.longitude]})
    
    return auto.create_incident(
        caller_name=incident.caller_name,
        classification=incident.classification,
        location=incident.location,
        attachment_id=incident.attachment_id or "",
        coordinates=coordinates,
        channel=incident.channel,
        national_id=incident.national_id,
        criticality=incident.criticality,
    )
 
 
@mcp.tool()
def get_classifications():
    """Get the list of valid incident classifications."""
    return auto.get_classifications()
 
 
@mcp.tool()
def get_locations():
    """Get the list of valid incident locations."""
    return auto.get_locations()

 
if __name__ == "__main__":
    # Run on port 8001 to avoid conflict with main FastAPI backend on 8000
    # Using streamable-http transport (recommended over deprecated SSE)
    print("Starting MCP Tool Server on http://localhost:8001/mcp")
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8001)
