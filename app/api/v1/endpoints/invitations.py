"""
User Invitations API Endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.schemas.user_invitation import (
    UserInvitationCreate,
    UserInvitationResponse,
    UserInvitationListItem,
    AcceptInvitationRequest,
    ValidateInvitationResponse
)
from app.services import invitation_service
from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.models.user import User

router = APIRouter()


@router.post("/", response_model=UserInvitationResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("user:create"))])
async def create_invitation(
    invitation_data: UserInvitationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Create a new invitation and optionally send email.
    Returns the invitation with a copy-able link.
    """
    try:
        invitation = invitation_service.create_invitation(
            db=db,
            invitation_data=invitation_data,
            company_id=current_user.company_id,
            invited_by_id=current_user.id
        )

        # Try to send email (non-blocking if SMTP not configured)
        await invitation_service.send_invitation_email(db, invitation, current_user.company_id)

        # Build response with invitation link
        invitation_link = invitation_service.get_invitation_link(invitation.token)

        # Get inviter name
        inviter_name = None
        if current_user.first_name and current_user.last_name:
            inviter_name = f"{current_user.first_name} {current_user.last_name}"
        elif current_user.first_name:
            inviter_name = current_user.first_name
        else:
            inviter_name = current_user.email

        # Get role name
        role_name = None
        if invitation.role:
            role_name = invitation.role.name

        return UserInvitationResponse(
            id=invitation.id,
            email=invitation.email,
            role_id=invitation.role_id,
            role_name=role_name,
            expires_at=invitation.expires_at,
            used_at=invitation.used_at,
            created_at=invitation.created_at,
            invitation_link=invitation_link,
            invited_by_name=inviter_name
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/", response_model=List[UserInvitationListItem],
            dependencies=[Depends(require_permission("user:read"))])
def list_pending_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    List all pending invitations for the current company.
    """
    invitations = invitation_service.get_pending_invitations(db, current_user.company_id)

    result = []
    for inv in invitations:
        # Get inviter name
        inviter_name = None
        if inv.invited_by:
            if inv.invited_by.first_name and inv.invited_by.last_name:
                inviter_name = f"{inv.invited_by.first_name} {inv.invited_by.last_name}"
            elif inv.invited_by.first_name:
                inviter_name = inv.invited_by.first_name
            else:
                inviter_name = inv.invited_by.email

        # Get role name
        role_name = None
        if inv.role:
            role_name = inv.role.name

        # Check if expired
        is_expired = inv.expires_at < datetime.utcnow()

        result.append(UserInvitationListItem(
            id=inv.id,
            email=inv.email,
            role_id=inv.role_id,
            role_name=role_name,
            expires_at=inv.expires_at,
            used_at=inv.used_at,
            created_at=inv.created_at,
            invited_by_name=inviter_name,
            is_expired=is_expired
        ))

    return result


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_permission("user:delete"))])
def revoke_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Revoke/delete a pending invitation.
    """
    success = invitation_service.revoke_invitation(db, invitation_id, current_user.company_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    return None


@router.post("/{invitation_id}/resend", response_model=UserInvitationResponse,
             dependencies=[Depends(require_permission("user:create"))])
async def resend_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Resend invitation email - generates new token and resets expiry.
    """
    invitation = await invitation_service.resend_invitation(db, invitation_id, current_user.company_id)

    if not invitation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found or already used")

    # Build response
    invitation_link = invitation_service.get_invitation_link(invitation.token)

    # Reload relationships
    db.refresh(invitation)

    role_name = None
    if invitation.role_id:
        from app.models.role import Role
        role = db.query(Role).filter(Role.id == invitation.role_id).first()
        if role:
            role_name = role.name

    inviter_name = None
    if current_user.first_name and current_user.last_name:
        inviter_name = f"{current_user.first_name} {current_user.last_name}"
    elif current_user.first_name:
        inviter_name = current_user.first_name
    else:
        inviter_name = current_user.email

    return UserInvitationResponse(
        id=invitation.id,
        email=invitation.email,
        role_id=invitation.role_id,
        role_name=role_name,
        expires_at=invitation.expires_at,
        used_at=invitation.used_at,
        created_at=invitation.created_at,
        invitation_link=invitation_link,
        invited_by_name=inviter_name
    )


# Public endpoints (no auth required)

@router.get("/validate/{token}", response_model=ValidateInvitationResponse)
def validate_invitation(
    token: str,
    db: Session = Depends(get_db)
):
    """
    Validate an invitation token (public endpoint).
    Returns invitation details if valid.
    """
    result = invitation_service.validate_invitation(db, token)
    return ValidateInvitationResponse(**result)


@router.post("/accept", status_code=status.HTTP_201_CREATED)
def accept_invitation(
    request: AcceptInvitationRequest,
    db: Session = Depends(get_db)
):
    """
    Accept an invitation and create user account (public endpoint).
    """
    try:
        user = invitation_service.accept_invitation(
            db=db,
            token=request.token,
            password=request.password,
            first_name=request.first_name,
            last_name=request.last_name
        )

        return {
            "success": True,
            "message": "Account created successfully. You can now log in.",
            "email": user.email
        }

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
