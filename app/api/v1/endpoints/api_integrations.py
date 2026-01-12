"""
API Integration Management Endpoints

Internal endpoints for managing API integrations.
Authenticated via JWT token (standard user auth).
"""
import hashlib
import hmac
import json
import httpx
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.api_integration import ApiIntegration
from app.services import api_key_service
from app.services.api_channel_service import (
    get_api_integration,
    get_api_integrations_by_company,
    create_api_integration,
    update_api_integration,
    delete_api_integration
)
from app.schemas.api_channel import (
    ApiIntegrationCreate, ApiIntegrationUpdate,
    ApiIntegrationResponse, ApiStatusResponse
)

router = APIRouter()


def _integration_to_response(integration: ApiIntegration) -> ApiIntegrationResponse:
    """Convert ApiIntegration model to response schema."""
    response = ApiIntegrationResponse(
        id=integration.id,
        name=integration.name,
        description=integration.description,
        api_key_id=integration.api_key_id,
        company_id=integration.company_id,
        webhook_url=integration.webhook_url,
        webhook_enabled=integration.webhook_enabled,
        sync_response=integration.sync_response,
        default_agent_id=integration.default_agent_id,
        default_workflow_id=integration.default_workflow_id,
        rate_limit_requests=integration.rate_limit_requests,
        rate_limit_window=integration.rate_limit_window,
        is_active=integration.is_active,
        created_at=integration.created_at,
        updated_at=integration.updated_at
    )

    # Include API key info without exposing the full key
    if integration.api_key:
        response.api_key_name = integration.api_key.name
        response.api_key_prefix = integration.api_key.key[:8] + "..." if integration.api_key.key else None

    return response


@router.get("/", response_model=List[ApiIntegrationResponse])
def list_integrations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all API integrations for the company."""
    integrations = get_api_integrations_by_company(db, current_user.company_id)
    return [_integration_to_response(i) for i in integrations]


@router.post("/", response_model=ApiIntegrationResponse, status_code=status.HTTP_201_CREATED)
def create_integration(
    integration_data: ApiIntegrationCreate,
    api_key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new API integration.

    Requires an existing API key ID to link to.
    Each API key can only have one integration.
    """
    # Verify API key belongs to company
    api_key = api_key_service.get_api_key_by_id(db, api_key_id)
    if not api_key or api_key.company_id != current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )

    # Check if integration already exists for this key
    existing = db.query(ApiIntegration).filter(
        ApiIntegration.api_key_id == api_key_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An integration already exists for this API key"
        )

    # Validate default agent/workflow if provided
    if integration_data.default_agent_id:
        from app.services import agent_service
        agent = agent_service.get_agent(db, integration_data.default_agent_id, current_user.company_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Default agent not found"
            )

    if integration_data.default_workflow_id:
        from app.services import workflow_service
        workflow = workflow_service.get_workflow(db, integration_data.default_workflow_id, current_user.company_id)
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Default workflow not found"
            )

    integration = create_api_integration(
        db,
        api_key_id=api_key_id,
        company_id=current_user.company_id,
        data=integration_data.model_dump()
    )

    return _integration_to_response(integration)


@router.get("/{integration_id}", response_model=ApiIntegrationResponse)
def get_integration_detail(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get API integration details."""
    integration = get_api_integration(db, integration_id, current_user.company_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )
    return _integration_to_response(integration)


@router.patch("/{integration_id}", response_model=ApiIntegrationResponse)
def update_integration_endpoint(
    integration_id: int,
    update_data: ApiIntegrationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an API integration."""
    integration = get_api_integration(db, integration_id, current_user.company_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )

    # Validate default agent/workflow if being updated
    if update_data.default_agent_id is not None:
        from app.services import agent_service
        if update_data.default_agent_id:
            agent = agent_service.get_agent(db, update_data.default_agent_id, current_user.company_id)
            if not agent:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Default agent not found"
                )

    if update_data.default_workflow_id is not None:
        from app.services import workflow_service
        if update_data.default_workflow_id:
            workflow = workflow_service.get_workflow(db, update_data.default_workflow_id, current_user.company_id)
            if not workflow:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Default workflow not found"
                )

    updated = update_api_integration(
        db, integration, update_data.model_dump(exclude_unset=True)
    )

    return _integration_to_response(updated)


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_integration_endpoint(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete an API integration."""
    integration = get_api_integration(db, integration_id, current_user.company_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )

    delete_api_integration(db, integration)
    return


@router.post("/{integration_id}/test-webhook", response_model=ApiStatusResponse)
async def test_webhook(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Test the webhook configuration by sending a test payload."""
    integration = get_api_integration(db, integration_id, current_user.company_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )

    if not integration.webhook_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook URL not configured"
        )

    test_payload = {
        "event_type": "test",
        "session_id": "test_session",
        "external_user_id": "test_user",
        "message": "This is a test webhook payload from AgentConnect",
        "status": "test",
        "timestamp": datetime.utcnow().isoformat(),
        "metadata": {"test": True}
    }

    payload_json = json.dumps(test_payload, sort_keys=True)
    signature = hmac.new(
        (integration.webhook_secret or "").encode(),
        payload_json.encode(),
        hashlib.sha256
    ).hexdigest()

    test_payload["signature"] = signature

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                integration.webhook_url,
                json=test_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": signature
                }
            )

            if response.is_success:
                return ApiStatusResponse(
                    status="success",
                    message=f"Webhook test sent successfully. Response status: {response.status_code}"
                )
            else:
                return ApiStatusResponse(
                    status="failed",
                    message=f"Webhook returned status {response.status_code}: {response.text[:200]}"
                )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Webhook request timed out"
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to connect to webhook URL"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to reach webhook URL: {str(e)}"
        )


@router.post("/{integration_id}/regenerate-secret", response_model=ApiStatusResponse)
def regenerate_webhook_secret(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Regenerate the webhook secret for an integration."""
    import secrets

    integration = get_api_integration(db, integration_id, current_user.company_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )

    # Generate new secret
    new_secret = secrets.token_urlsafe(32)
    integration.webhook_secret = new_secret
    db.commit()

    return ApiStatusResponse(
        status="success",
        message=f"Webhook secret regenerated. New secret: {new_secret}"
    )
