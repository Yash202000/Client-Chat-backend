from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
import google_auth_oauthlib.flow
import logging
import json
from jose import JWTError, jwt

from app.core.config import settings
from app.core.dependencies import get_db
from app.services import credential_service, user_service, integration_service
from app.schemas import credential as schemas_credential, token as schemas_token, integration as schemas_integration
from app.models.user import User

router = APIRouter()

async def get_user_from_token(db: Session, token: str) -> User:
    """Helper function to decode JWT from state and return a user."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            return None
        token_data = schemas_token.TokenData(email=email)
    except JWTError:
        return None
    
    user = user_service.get_user_by_email(db, email=token_data.email)
    return user

@router.get("/client-id")
def get_google_client_id():
    return {"client_id": settings.GOOGLE_CLIENT_ID}

@router.get("/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    """
    Handles the unified OAuth 2.0 callback from Google.
    Authenticates the user via the JWT passed in the 'state' parameter.
    """
    code = request.query_params.get("code")
    token = request.query_params.get("state")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    if not token:
        raise HTTPException(status_code=400, detail="Missing state token")

    current_user = await get_user_from_token(db, token)
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials from state token",
        )

    try:
        # The redirect_uri must match the one registered in the Google Cloud Console
        redirect_uri = 'http://localhost:8080/api/v1/google/callback'

        client_config = {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uris": [redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config,
            scopes=[
                'openid',
                'https://www.googleapis.com/auth/gmail.modify',
                'https://www.googleapis.com/auth/calendar',
                'https://www.googleapis.com/auth/userinfo.email'
            ],
            redirect_uri=redirect_uri
        )
        
        # Disable strict scope checking - Google may return different scopes than requested
        import os
        os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
        
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Fetch the authenticated user's email from Google
        # Use a direct HTTP call to avoid the API client triggering a scope-mismatched token refresh
        import requests as http_requests
        try:
            userinfo_resp = http_requests.get(
                'https://www.googleapis.com/oauth2/v2/userinfo',
                headers={'Authorization': f'Bearer {credentials.token}'}
            )
            user_email = userinfo_resp.json().get('email') if userinfo_resp.status_code == 200 else None
        except Exception:
            user_email = None

        # Check if a credential for 'google' service already exists and update it, or create a new one.
        db_credential = credential_service.get_credential_by_service_name(db, service_name='google', company_id=current_user.company_id)
        
        credential_data = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'expiry': credentials.expiry.isoformat() if credentials.expiry else None,
            'user_email': user_email,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': list(credentials.scopes) if credentials.scopes else []  # Convert to list for JSON
        }
        
        credentials_json = json.dumps(credential_data)

        if db_credential:
            credential_schema = schemas_credential.CredentialUpdate(credentials=credentials_json)
            credential_service.update_credential(db, credential_id=db_credential.id, credential=credential_schema, company_id=current_user.company_id)
        else:
            credential_schema = schemas_credential.CredentialCreate(name="Google Credential", service='google', credentials=credentials_json)
            credential_service.create_credential(db, credential=credential_schema, company_id=current_user.company_id)

        # Validate that we have the required credentials before saving integrations
        if not credential_data.get('refresh_token'):
            raise Exception("OAuth did not return a refresh_token. Please revoke app access in Google Account and try again.")

        # Create or update the Gmail integration
        db_integration = integration_service.get_integration_by_type_and_company(db, integration_type='gmail', company_id=current_user.company_id)
        if db_integration:
            integration_schema = schemas_integration.IntegrationUpdate(enabled=True, credentials=credential_data)
            integration_service.update_integration(db, db_integration=db_integration, integration_in=integration_schema)
        else:
            integration_schema = schemas_integration.IntegrationCreate(name="Gmail", type='gmail', enabled=True, credentials=credential_data)
            integration_service.create_integration(db, integration=integration_schema, company_id=current_user.company_id)

        # Also create or update Google Calendar integration (same credentials)
        db_calendar_integration = integration_service.get_integration_by_type_and_company(db, integration_type='google_calendar', company_id=current_user.company_id)
        if db_calendar_integration:
            integration_schema = schemas_integration.IntegrationUpdate(enabled=True, credentials=credential_data)
            integration_service.update_integration(db, db_integration=db_calendar_integration, integration_in=integration_schema)
        else:
            integration_schema = schemas_integration.IntegrationCreate(name="Google Calendar", type='google_calendar', enabled=True, credentials=credential_data)
            integration_service.create_integration(db, integration=integration_schema, company_id=current_user.company_id)

        # This script securely closes the popup window and notifies the parent window of success.
        return Response(content="<script>window.opener.postMessage('google-success', '*');window.close();</script>", media_type="text/html")

    except Exception as e:
        import traceback
        logging.error(f"Error during Google OAuth callback: {e}")
        logging.error(traceback.format_exc())  # Log full stack trace
        raise HTTPException(status_code=500, detail=f"Failed to authenticate with Google: {str(e)}")
