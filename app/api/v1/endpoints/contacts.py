from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import hashlib

from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.services import contact_service, integration_service, messaging_service
from app.services.ticket_service import (
    get_crm_workflow, get_workflow_with_details, get_available_transitions, execute_entity_transition,
)
from app.schemas import contact as schemas_contact
from app.schemas.ticket import TicketTransitionExecute as TicketTransitionData
from app.models import conversation_session as models_conversation_session
from app.models import user as models_user
from app.models import integration as models_integration


def _gravatar_url(email: str) -> str:
    digest = hashlib.md5(email.strip().lower().encode()).hexdigest()
    return f"https://www.gravatar.com/avatar/{digest}?s=200&d=404"


def _resolve_profile_picture(contact) -> Optional[str]:
    """Returns the contact's stored picture, or a Gravatar URL if they have an email."""
    if contact.profile_picture_url:
        return contact.profile_picture_url
    if contact.email:
        return _gravatar_url(contact.email)
    return None

router = APIRouter()


@router.get("/workflow", dependencies=[Depends(require_permission("contact:read"))])
def get_contact_workflow(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """Return the contact workflow (statuses + transitions) for the current company."""
    wf = get_crm_workflow(db, current_user.company_id, "contact")
    if not wf:
        raise HTTPException(status_code=404, detail="Contact workflow not found")
    return get_workflow_with_details(db, wf.id)


@router.post("/{contact_id}/transition", response_model=schemas_contact.Contact, dependencies=[Depends(require_permission("contact:update"))])
def transition_contact(
    contact_id: int,
    data: TicketTransitionData,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    contact = contact_service.get_contact(db, contact_id=contact_id, company_id=current_user.company_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    execute_entity_transition(db, contact, data.transition_id, data, current_user.company_id, current_user.id)
    db.refresh(contact)
    contact.available_transitions = get_available_transitions(db, contact.workflow_id, contact.status_id)
    return contact


@router.get("/", response_model=List[schemas_contact.Contact], dependencies=[Depends(require_permission("contact:read"))])
def read_contacts(
    skip: int = 0,
    limit: int = 100,
    tag_ids: Optional[List[int]] = Query(None, description="Filter by tag IDs"),
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    contacts = contact_service.get_contacts(db, company_id=current_user.company_id, skip=skip, limit=limit, tag_ids=tag_ids)
    # Map tag_objects to tags for each contact
    result = []
    for contact in contacts:
        contact_dict = {
            "id": contact.id,
            "company_id": contact.company_id,
            "email": contact.email,
            "name": contact.name,
            "phone_number": contact.phone_number,
            "custom_attributes": contact.custom_attributes,
            "lead_source": contact.lead_source,
            "lifecycle_stage": contact.lifecycle_stage,
            "do_not_contact": contact.do_not_contact,
            "opt_in_status": contact.opt_in_status,
            "opt_in_date": contact.opt_in_date,
            "opt_out_date": contact.opt_out_date,
            "created_at": contact.created_at,
            "updated_at": contact.updated_at,
            "last_contacted_at": contact.last_contacted_at,
            "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in contact.tag_objects] if hasattr(contact, 'tag_objects') else [],
            "profile_picture_url": _resolve_profile_picture(contact),
            "workflow_id": contact.workflow_id,
            "status_id": contact.status_id,
            "wf_status": {"id": contact.status.id, "name": contact.status.name, "color": contact.status.color, "category": contact.status.category} if getattr(contact, 'status', None) else None,
            "available_transitions": get_available_transitions(db, contact.workflow_id, contact.status_id) if contact.workflow_id and contact.status_id else [],
        }
        result.append(contact_dict)
    return result

@router.get("/{contact_id}", response_model=schemas_contact.Contact, dependencies=[Depends(require_permission("contact:read"))])
def read_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_contact = contact_service.get_contact(db, contact_id=contact_id, company_id=current_user.company_id)
    if db_contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact

@router.put("/{contact_id}", response_model=schemas_contact.Contact, dependencies=[Depends(require_permission("contact:update"))])
def update_contact(
    contact_id: int,
    contact: schemas_contact.ContactUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return contact_service.update_contact(db=db, contact_id=contact_id, contact=contact, company_id=current_user.company_id)

@router.post("/{contact_id}/refresh_profile_picture", dependencies=[Depends(require_permission("contact:update"))])
async def refresh_contact_profile_picture(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Attempts to re-fetch a contact's profile picture from their channel (e.g. WhatsApp).
    Safe to call multiple times; no-ops if the channel integration is missing.
    """
    contact = contact_service.get_contact(db, contact_id=contact_id, company_id=current_user.company_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    phone = contact.phone_number
    wa_id = contact.custom_attributes.get("whatsapp_id") if contact.custom_attributes else None
    lookup_phone = wa_id or phone

    if not lookup_phone:
        return {"profile_picture_url": None, "message": "No phone number on contact"}

    # Find the company's WhatsApp integration
    integration = db.query(models_integration.Integration).filter(
        models_integration.Integration.company_id == current_user.company_id,
        models_integration.Integration.type == "whatsapp",
        models_integration.Integration.enabled == True
    ).first()

    if not integration:
        return {"profile_picture_url": None, "message": "No active WhatsApp integration"}

    pic_url = await messaging_service.fetch_whatsapp_profile_picture(
        wa_id=lookup_phone,
        integration=integration,
        db=db
    )

    if pic_url:
        contact.profile_picture_url = pic_url
        db.commit()
        db.refresh(contact)

    return {"profile_picture_url": contact.profile_picture_url}


@router.get("/by_session/{session_id}", response_model=Optional[schemas_contact.Contact], dependencies=[Depends(require_permission("contact:read"))])
def get_contact_by_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get contact for a session. Returns null if session has no contact (anonymous sessions).
    """
    session = db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.conversation_id == str(session_id),
        models_conversation_session.ConversationSession.company_id == current_user.company_id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Return null if session has no contact (anonymous session)
    if not session.contact:
        return None

    contact = session.contact
    contact_dict = {
        "id": contact.id,
        "company_id": contact.company_id,
        "email": contact.email,
        "name": contact.name,
        "phone_number": contact.phone_number,
        "custom_attributes": contact.custom_attributes,
        "lead_source": contact.lead_source,
        "lifecycle_stage": contact.lifecycle_stage,
        "do_not_contact": contact.do_not_contact,
        "opt_in_status": contact.opt_in_status,
        "opt_in_date": contact.opt_in_date,
        "opt_out_date": contact.opt_out_date,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
        "last_contacted_at": contact.last_contacted_at,
        "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in contact.tag_objects] if hasattr(contact, 'tag_objects') else [],
        "profile_picture_url": _resolve_profile_picture(contact),
        # Profile fields
        "job_title": contact.job_title,
        "company_name": contact.company_name,
        "location": contact.location,
        "website": contact.website,
        "linkedin_url": contact.linkedin_url,
        "instagram_handle": contact.instagram_handle,
        "facebook_url": contact.facebook_url,
        # Channel the conversation came through
        "channel": session.channel,
    }
    return contact_dict
