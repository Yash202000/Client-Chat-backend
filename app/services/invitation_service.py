"""
Invitation Service
Handles user invitations - create, validate, accept, revoke
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session, joinedload

from app.models.user_invitation import UserInvitation
from app.models.user import User
from app.models.company import Company
from app.models.company_settings import CompanySettings
from app.models.role import Role
from app.schemas.user_invitation import UserInvitationCreate, AcceptInvitationRequest
from app.services import user_service
from app.services.email_service import send_email_smtp
from app.schemas.user import UserCreate
from app.core.config import settings


INVITATION_EXPIRY_HOURS = 24


def generate_invitation_token() -> str:
    """Generate a secure random token for invitation links"""
    return secrets.token_urlsafe(32)


def get_invitation_link(token: str) -> str:
    """Generate the full invitation link"""
    # Use frontend URL from settings or default
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
    return f"{frontend_url}/accept-invite?token={token}"


def create_invitation(
    db: Session,
    invitation_data: UserInvitationCreate,
    company_id: int,
    invited_by_id: int
) -> UserInvitation:
    """
    Create a new invitation and optionally send email
    """
    # Check if user already exists with this email
    existing_user = user_service.get_user_by_email(db, invitation_data.email)
    if existing_user and existing_user.company_id == company_id:
        raise ValueError("A user with this email already exists in your company")

    # Check if there's already a pending invitation for this email
    existing_invitation = db.query(UserInvitation).filter(
        UserInvitation.email == invitation_data.email,
        UserInvitation.company_id == company_id,
        UserInvitation.used_at.is_(None),
        UserInvitation.expires_at > datetime.utcnow()
    ).first()

    if existing_invitation:
        raise ValueError("An invitation has already been sent to this email")

    # Generate token and expiry
    token = generate_invitation_token()
    expires_at = datetime.utcnow() + timedelta(hours=INVITATION_EXPIRY_HOURS)

    # Create invitation
    invitation = UserInvitation(
        email=invitation_data.email,
        token=token,
        role_id=invitation_data.role_id,
        company_id=company_id,
        invited_by_id=invited_by_id,
        expires_at=expires_at
    )

    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    return invitation


async def send_invitation_email(
    db: Session,
    invitation: UserInvitation,
    company_id: int
) -> bool:
    """
    Send invitation email using company's SMTP settings
    """
    # Get company settings for SMTP
    company_settings = db.query(CompanySettings).filter(
        CompanySettings.company_id == company_id
    ).first()

    if not company_settings or not company_settings.smtp_host:
        print(f"[INVITATION] SMTP not configured for company {company_id}, skipping email")
        return False

    # Get company and inviter info
    company = db.query(Company).filter(Company.id == company_id).first()
    inviter = db.query(User).filter(User.id == invitation.invited_by_id).first()

    # Get role name if set
    role_name = "Team Member"
    if invitation.role_id:
        role = db.query(Role).filter(Role.id == invitation.role_id).first()
        if role:
            role_name = role.name

    inviter_name = "Your administrator"
    if inviter:
        if inviter.first_name and inviter.last_name:
            inviter_name = f"{inviter.first_name} {inviter.last_name}"
        elif inviter.first_name:
            inviter_name = inviter.first_name
        else:
            inviter_name = inviter.email

    company_name = company.name if company else "the team"
    invitation_link = get_invitation_link(invitation.token)

    # Build email content
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
            <h1 style="color: white; margin: 0; font-size: 28px;">You're Invited!</h1>
        </div>
        <div style="background: #ffffff; padding: 30px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
            <p style="font-size: 16px; margin-bottom: 20px;">
                <strong>{inviter_name}</strong> has invited you to join <strong>{company_name}</strong>.
            </p>
            <p style="font-size: 14px; color: #666; margin-bottom: 20px;">
                Role: <strong>{role_name}</strong>
            </p>
            <div style="text-align: center; margin: 30px 0;">
                <a href="{invitation_link}" style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; padding: 14px 30px; border-radius: 6px; font-weight: 600; font-size: 16px;">
                    Accept Invitation
                </a>
            </div>
            <p style="font-size: 12px; color: #999; text-align: center; margin-top: 30px;">
                This invitation link will expire in {INVITATION_EXPIRY_HOURS} hours.
            </p>
            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 12px; color: #999; text-align: center;">
                If you didn't expect this invitation, you can safely ignore this email.
            </p>
        </div>
    </body>
    </html>
    """

    text_content = f"""
You're Invited!

{inviter_name} has invited you to join {company_name}.

Role: {role_name}

Click the link below to accept the invitation:
{invitation_link}

This invitation link will expire in {INVITATION_EXPIRY_HOURS} hours.

If you didn't expect this invitation, you can safely ignore this email.
    """

    smtp_config = {
        'host': company_settings.smtp_host,
        'port': company_settings.smtp_port or 587,
        'user': company_settings.smtp_user,
        'password': company_settings.smtp_password,
        'use_tls': company_settings.smtp_use_tls if hasattr(company_settings, 'smtp_use_tls') else True
    }

    try:
        await send_email_smtp(
            to_email=invitation.email,
            subject=f"You've been invited to join {company_name}",
            html_content=html_content,
            text_content=text_content,
            from_email=company_settings.smtp_from_email or company_settings.smtp_user,
            from_name=company_settings.smtp_from_name or company_name,
            smtp_config=smtp_config
        )
        print(f"[INVITATION] Email sent to {invitation.email}")
        return True
    except Exception as e:
        print(f"[INVITATION] Failed to send email: {e}")
        return False


def get_invitation_by_token(db: Session, token: str) -> Optional[UserInvitation]:
    """Get invitation by token with eager loading of relationships"""
    return db.query(UserInvitation).options(
        joinedload(UserInvitation.role),
        joinedload(UserInvitation.company),
        joinedload(UserInvitation.invited_by)
    ).filter(UserInvitation.token == token).first()


def validate_invitation(db: Session, token: str) -> dict:
    """
    Validate invitation token and return details
    """
    invitation = get_invitation_by_token(db, token)

    if not invitation:
        return {"valid": False, "error": "Invalid invitation link"}

    if invitation.used_at:
        return {"valid": False, "error": "This invitation has already been used"}

    if invitation.expires_at < datetime.utcnow():
        return {"valid": False, "error": "This invitation has expired"}

    role_name = invitation.role.name if invitation.role else "Team Member"
    company_name = invitation.company.name if invitation.company else ""

    return {
        "valid": True,
        "email": invitation.email,
        "company_name": company_name,
        "role_name": role_name,
        "expires_at": invitation.expires_at
    }


def accept_invitation(
    db: Session,
    token: str,
    password: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None
) -> User:
    """
    Accept invitation and create user account
    """
    invitation = get_invitation_by_token(db, token)

    if not invitation:
        raise ValueError("Invalid invitation link")

    if invitation.used_at:
        raise ValueError("This invitation has already been used")

    if invitation.expires_at < datetime.utcnow():
        raise ValueError("This invitation has expired")

    # Check if user already exists
    existing_user = user_service.get_user_by_email(db, invitation.email)
    if existing_user:
        raise ValueError("A user with this email already exists")

    # Create user
    user_create = UserCreate(
        email=invitation.email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        role_id=invitation.role_id
    )

    new_user = user_service.create_user(
        db=db,
        user=user_create,
        company_id=invitation.company_id,
        role_id=invitation.role_id
    )

    # Mark invitation as used
    invitation.used_at = datetime.utcnow()
    db.commit()

    return new_user


def get_pending_invitations(db: Session, company_id: int) -> List[UserInvitation]:
    """Get all pending (unused) invitations for a company"""
    return db.query(UserInvitation).options(
        joinedload(UserInvitation.role),
        joinedload(UserInvitation.invited_by)
    ).filter(
        UserInvitation.company_id == company_id,
        UserInvitation.used_at.is_(None)
    ).order_by(UserInvitation.created_at.desc()).all()


def revoke_invitation(db: Session, invitation_id: int, company_id: int) -> bool:
    """Delete/revoke a pending invitation"""
    invitation = db.query(UserInvitation).filter(
        UserInvitation.id == invitation_id,
        UserInvitation.company_id == company_id
    ).first()

    if not invitation:
        return False

    db.delete(invitation)
    db.commit()
    return True


async def resend_invitation(db: Session, invitation_id: int, company_id: int) -> Optional[UserInvitation]:
    """
    Resend invitation - reset expiry and send email again
    """
    invitation = db.query(UserInvitation).filter(
        UserInvitation.id == invitation_id,
        UserInvitation.company_id == company_id,
        UserInvitation.used_at.is_(None)
    ).first()

    if not invitation:
        return None

    # Generate new token and reset expiry
    invitation.token = generate_invitation_token()
    invitation.expires_at = datetime.utcnow() + timedelta(hours=INVITATION_EXPIRY_HOURS)
    db.commit()
    db.refresh(invitation)

    # Send email
    await send_invitation_email(db, invitation, company_id)

    return invitation
