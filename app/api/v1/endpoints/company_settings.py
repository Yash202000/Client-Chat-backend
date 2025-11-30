
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.schemas import company_settings as schemas_company_settings
from app.services import company_settings_service, email_service
from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.models import user as models_user

router = APIRouter()

@router.get("/", response_model=schemas_company_settings.CompanySettings)
def read_company_settings(db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    settings = company_settings_service.get_company_settings(db, company_id=current_user.company_id)
    if not settings:
        username = current_user.email.split('@')[0]
        # If no settings exist, create them with default values
        default_settings = schemas_company_settings.CompanySettingsCreate(
            company_name=f"{username}'s company",
            support_email=current_user.email,
            timezone="UTC",
            language="en",
            business_hours=True
        )
        return company_settings_service.create_company_settings(db, current_user.company_id, default_settings)
    return settings

@router.put("/", response_model=schemas_company_settings.CompanySettings, dependencies=[Depends(require_permission("company_settings:update"))])
def update_company_settings(settings: schemas_company_settings.CompanySettingsUpdate, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    return company_settings_service.update_company_settings(db, company_id=current_user.company_id, settings=settings)


@router.post("/test-smtp", dependencies=[Depends(require_permission("company_settings:update"))])
async def test_smtp_configuration(
    request: schemas_company_settings.SMTPTestRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Test SMTP configuration by sending a test email
    """
    # Get current company settings to use as defaults
    settings = company_settings_service.get_company_settings(db, company_id=current_user.company_id)

    # Build SMTP config from request or fall back to saved settings
    smtp_config = {
        'host': request.smtp_host or (settings.smtp_host if settings else None),
        'port': request.smtp_port or (settings.smtp_port if settings else 587),
        'user': request.smtp_user or (settings.smtp_user if settings else None),
        'password': request.smtp_password or (settings.smtp_password if settings else None),
        'use_tls': request.smtp_use_tls if request.smtp_use_tls is not None else (settings.smtp_use_tls if settings else True),
    }

    from_email = request.smtp_from_email or (settings.smtp_from_email if settings else None)
    from_name = request.smtp_from_name or (settings.smtp_from_name if settings else 'AgentConnect')

    # Validate required fields
    if not all([smtp_config['host'], smtp_config['user'], smtp_config['password']]):
        raise HTTPException(
            status_code=400,
            detail="SMTP host, user, and password are required"
        )

    try:
        result = await email_service.send_email_smtp(
            to_email=request.to_email,
            subject="Test Email from AgentConnect",
            html_content="""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #0891b2;">SMTP Configuration Test</h2>
                <p>Congratulations! Your SMTP settings are configured correctly.</p>
                <p>This is a test email sent from AgentConnect to verify your email configuration.</p>
                <hr style="border: 1px solid #e5e7eb; margin: 20px 0;">
                <p style="color: #6b7280; font-size: 12px;">
                    This email was sent as part of the SMTP configuration test.
                </p>
            </body>
            </html>
            """,
            text_content="SMTP Configuration Test\n\nCongratulations! Your SMTP settings are configured correctly.\n\nThis is a test email sent from AgentConnect to verify your email configuration.",
            from_email=from_email,
            from_name=from_name,
            smtp_config=smtp_config
        )
        return {"success": True, "message": f"Test email sent successfully to {request.to_email}"}
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to send test email: {str(e)}"
        )
