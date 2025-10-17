from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import requests
from app.core.config import settings
from app.core.dependencies import get_db
from app.services import integration_service
from app.schemas.integration import IntegrationCreate

router = APIRouter()

@router.get("/teams/callback")
def teams_calendar_callback(request: Request, db: Session = Depends(get_db)):
    """
    Handles the OAuth 2.0 callback from Microsoft Teams.
    """
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Replace with your Microsoft Teams app credentials
    tenant_id = "YOUR_TENANT_ID"
    client_id = "YOUR_TEAMS_CLIENT_ID"
    client_secret = "YOUR_TEAMS_CLIENT_SECRET"
    redirect_uri = "http://localhost:8080/api/v1/teams/callback"  # Make sure this matches your app registration

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "scope": "https://graph.microsoft.com/.default"
    }
    token_response = requests.post(token_url, data=data)

    if token_response.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Failed to retrieve access token: {token_response.text}")

    token_data = token_response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    # Get user info from Microsoft Graph API
    user_info_url = "https://graph.microsoft.com/v1.0/me"
    headers = {"Authorization": f"Bearer {access_token}"}
    user_info_response = requests.get(user_info_url, headers=headers)

    if user_info_response.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Failed to retrieve user info: {user_info_response.text}")

    user_info = user_info_response.json()
    user_email = user_info.get("mail")

    company_id = 1  # Placeholder

    integration_data = IntegrationCreate(
        name=f"Microsoft Teams Calendar - {user_email}",
        type="teams_calendar",
        credentials={
            "user_email": user_email,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }
    )
    
    integration_service.create_integration(db, integration=integration_data, company_id=company_id)

    return {"status": "success", "message": "Microsoft Teams Calendar connected successfully."}
