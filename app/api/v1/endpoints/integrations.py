from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.core.dependencies import get_db, get_current_active_user, get_current_company
from app.models import user as models_user
from app.schemas import integration as schemas_integration
from app.services import integration_service
from app.services.whatsapp_token_service import whatsapp_token_service, WhatsAppTokenError
from app.services.whatsapp_token_refresh_service import get_token_status_for_integration

router = APIRouter()

@router.post("/", response_model=schemas_integration.Integration)
def create_integration(
    integration: schemas_integration.IntegrationCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Create a new integration for the current user's company.
    """
    # TODO: Add permission check to ensure user is a company admin
    return integration_service.create_integration(db=db, integration=integration, company_id=current_user.company_id)

@router.get("/", response_model=List[schemas_integration.Integration])
def read_integrations(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Retrieve all integrations for the current user's company.
    """
    return integration_service.get_integrations_by_company(db, company_id=current_user.company_id)

@router.get("/{integration_id}", response_model=schemas_integration.Integration)
def read_integration(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Retrieve a specific integration by ID.
    """
    db_integration = integration_service.get_integration(db, integration_id=integration_id, company_id=current_user.company_id)
    if db_integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    return db_integration

@router.put("/{integration_id}", response_model=schemas_integration.Integration)
def update_integration(
    integration_id: int,
    integration_in: schemas_integration.IntegrationUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update an integration.
    """
    db_integration = integration_service.get_integration(db, integration_id=integration_id, company_id=current_user.company_id)
    if db_integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    # TODO: Add permission check
    return integration_service.update_integration(db=db, db_integration=db_integration, integration_in=integration_in)

@router.delete("/{integration_id}", response_model=schemas_integration.Integration)
def delete_integration(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Delete an integration.
    """
    db_integration = integration_service.delete_integration(db, integration_id=integration_id, company_id=current_user.company_id)
    if db_integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    # TODO: Add permission check
    return db_integration


# WhatsApp OAuth Endpoints

@router.post("/{integration_id}/whatsapp/oauth/setup")
async def setup_whatsapp_oauth(
    integration_id: int,
    oauth_config: schemas_integration.WhatsAppOAuthSetup,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Configure OAuth credentials for a WhatsApp integration.

    This exchanges a short-lived token for a long-lived token and stores
    the OAuth credentials for automatic token refresh.

    Args:
        integration_id: The integration ID
        oauth_config: OAuth configuration including access_token, client_id, client_secret
    """
    # Get the integration
    db_integration = integration_service.get_integration(
        db, integration_id=integration_id, company_id=current_user.company_id
    )
    if not db_integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    if db_integration.type != "whatsapp":
        raise HTTPException(status_code=400, detail="This endpoint is only for WhatsApp integrations")

    try:
        # Exchange for long-lived token
        new_token, expires_in = await whatsapp_token_service.exchange_for_long_lived_token(
            short_lived_token=oauth_config.access_token,
            client_id=oauth_config.client_id,
            client_secret=oauth_config.client_secret
        )

        # Get existing credentials and update with OAuth info
        credentials = integration_service.get_decrypted_credentials(db_integration)
        credentials.update({
            "access_token": new_token,
            "phone_number_id": oauth_config.phone_number_id,
            "client_id": oauth_config.client_id,
            "client_secret": oauth_config.client_secret,
            "whatsapp_business_number": oauth_config.whatsapp_business_number,
            "token_type": "long_lived",
            "token_expires_at": int(datetime.utcnow().timestamp() + expires_in),
            "last_refresh_at": int(datetime.utcnow().timestamp()),
            "refresh_error": None
        })

        # Update integration
        update_schema = schemas_integration.IntegrationUpdate(credentials=credentials)
        integration_service.update_integration(db, db_integration, update_schema)

        return {
            "status": "success",
            "message": "OAuth configured successfully. Token will be refreshed automatically.",
            "token_type": "long_lived",
            "token_expires_at": datetime.fromtimestamp(credentials["token_expires_at"]).isoformat(),
            "hours_until_expiry": round(expires_in / 3600, 1)
        }

    except WhatsAppTokenError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{integration_id}/whatsapp/oauth/status", response_model=schemas_integration.WhatsAppOAuthStatus)
def get_whatsapp_oauth_status(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get OAuth token status for a WhatsApp integration.

    Returns information about:
    - Whether OAuth is enabled
    - Token type (short_lived, long_lived, legacy)
    - Token expiry time
    - Whether token needs refresh
    - Last refresh time and any errors
    """
    # Get the integration
    db_integration = integration_service.get_integration(
        db, integration_id=integration_id, company_id=current_user.company_id
    )
    if not db_integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    if db_integration.type != "whatsapp":
        raise HTTPException(status_code=400, detail="This endpoint is only for WhatsApp integrations")

    status = get_token_status_for_integration(db, integration_id, current_user.company_id)

    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])

    return status


@router.post("/{integration_id}/whatsapp/oauth/refresh")
async def refresh_whatsapp_token(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Manually refresh the WhatsApp OAuth token.

    This is useful for testing or when you want to force a token refresh
    before the automatic refresh kicks in.
    """
    # Get the integration
    db_integration = integration_service.get_integration(
        db, integration_id=integration_id, company_id=current_user.company_id
    )
    if not db_integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    if db_integration.type != "whatsapp":
        raise HTTPException(status_code=400, detail="This endpoint is only for WhatsApp integrations")

    credentials = whatsapp_token_service.get_credentials_with_expiry_check(db_integration)

    if not credentials.get("is_oauth_enabled"):
        raise HTTPException(
            status_code=400,
            detail="OAuth is not enabled for this integration. Use /oauth/setup first."
        )

    try:
        # Force refresh the token
        current_token = credentials.get("access_token") or credentials.get("api_token")
        new_token, expires_in = await whatsapp_token_service.refresh_token(
            current_token=current_token,
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"]
        )

        # Update credentials
        credentials.update({
            "access_token": new_token,
            "token_type": "long_lived",
            "token_expires_at": int(datetime.utcnow().timestamp() + expires_in),
            "last_refresh_at": int(datetime.utcnow().timestamp()),
            "refresh_error": None
        })

        # Remove internal flags
        credentials.pop("is_oauth_enabled", None)
        credentials.pop("needs_refresh", None)

        # Update integration
        update_schema = schemas_integration.IntegrationUpdate(credentials=credentials)
        integration_service.update_integration(db, db_integration, update_schema)

        return {
            "status": "success",
            "message": "Token refreshed successfully",
            "token_expires_at": datetime.fromtimestamp(credentials["token_expires_at"]).isoformat(),
            "hours_until_expiry": round(expires_in / 3600, 1)
        }

    except WhatsAppTokenError as e:
        raise HTTPException(status_code=400, detail=f"Token refresh failed: {str(e)}")
