from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.models.campaign_sequence_trigger import CampaignSequenceTrigger
from app.models.campaign import Campaign
from app.models.campaign_contact import CampaignContact, EnrollmentStatus
from app.models.sequence import Sequence, SequenceEnrollment

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class TriggerCreate(BaseModel):
    sequence_id: int
    trigger_condition: str
    delay_hours: int = 0


class TriggerUpdate(BaseModel):
    trigger_condition: Optional[str] = None
    delay_hours: Optional[int] = None
    is_active: Optional[bool] = None


class SequenceInfo(BaseModel):
    id: int
    name: str
    status: str

    class Config:
        from_attributes = True


class TriggerOut(BaseModel):
    id: int
    campaign_id: int
    sequence_id: int
    trigger_condition: str
    delay_hours: int
    is_active: bool
    last_fired_at: Optional[datetime] = None
    enrolled_count: int
    created_at: datetime
    sequence: Optional[SequenceInfo] = None

    class Config:
        from_attributes = True


CONDITION_LABELS = {
    "on_send":       "When campaign sends — enroll all",
    "on_completion": "When contact completes campaign",
    "if_opened":     "If contact opened an email",
    "if_not_opened": "If contact never opened",
    "if_clicked":    "If contact clicked a link",
    "if_not_clicked":"If contact never clicked",
    "if_replied":    "If contact replied",
    "if_not_replied":"If contact never replied",
}


def _matching_contact_ids(db: Session, campaign_id: int, condition: str) -> List[int]:
    """Return contact_ids from campaign_contacts matching the trigger condition."""
    base = db.query(CampaignContact).filter(CampaignContact.campaign_id == campaign_id)

    if condition == "on_send":
        rows = base.all()
    elif condition == "on_completion":
        rows = base.filter(CampaignContact.status == EnrollmentStatus.COMPLETED).all()
    elif condition == "if_opened":
        rows = base.filter(CampaignContact.opens > 0).all()
    elif condition == "if_not_opened":
        rows = base.filter(CampaignContact.opens == 0).all()
    elif condition == "if_clicked":
        rows = base.filter(CampaignContact.clicks > 0).all()
    elif condition == "if_not_clicked":
        rows = base.filter(CampaignContact.clicks == 0).all()
    elif condition == "if_replied":
        rows = base.filter(CampaignContact.replies > 0).all()
    elif condition == "if_not_replied":
        rows = base.filter(CampaignContact.replies == 0).all()
    else:
        rows = []

    return [r.contact_id for r in rows]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/sequence-triggers", response_model=List[TriggerOut])
def list_triggers(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id, Campaign.company_id == current_user.company_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return db.query(CampaignSequenceTrigger).filter(
        CampaignSequenceTrigger.campaign_id == campaign_id
    ).order_by(CampaignSequenceTrigger.created_at).all()


@router.post("/{campaign_id}/sequence-triggers", response_model=TriggerOut)
def create_trigger(
    campaign_id: int,
    data: TriggerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id, Campaign.company_id == current_user.company_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    sequence = db.query(Sequence).filter(
        Sequence.id == data.sequence_id, Sequence.company_id == current_user.company_id
    ).first()
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")

    if data.trigger_condition not in CONDITION_LABELS:
        raise HTTPException(status_code=400, detail=f"Unknown condition: {data.trigger_condition}")

    trigger = CampaignSequenceTrigger(
        campaign_id=campaign_id,
        sequence_id=data.sequence_id,
        trigger_condition=data.trigger_condition,
        delay_hours=data.delay_hours,
    )
    db.add(trigger)
    db.commit()
    db.refresh(trigger)
    return trigger


@router.put("/{campaign_id}/sequence-triggers/{trigger_id}", response_model=TriggerOut)
def update_trigger(
    campaign_id: int,
    trigger_id: int,
    data: TriggerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    trigger = db.query(CampaignSequenceTrigger).join(Campaign).filter(
        CampaignSequenceTrigger.id == trigger_id,
        CampaignSequenceTrigger.campaign_id == campaign_id,
        Campaign.company_id == current_user.company_id,
    ).first()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    for field, value in data.dict(exclude_none=True).items():
        setattr(trigger, field, value)
    db.commit()
    db.refresh(trigger)
    return trigger


@router.delete("/{campaign_id}/sequence-triggers/{trigger_id}")
def delete_trigger(
    campaign_id: int,
    trigger_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    trigger = db.query(CampaignSequenceTrigger).join(Campaign).filter(
        CampaignSequenceTrigger.id == trigger_id,
        CampaignSequenceTrigger.campaign_id == campaign_id,
        Campaign.company_id == current_user.company_id,
    ).first()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")
    db.delete(trigger)
    db.commit()
    return {"ok": True}


@router.post("/{campaign_id}/sequence-triggers/{trigger_id}/fire")
def fire_trigger(
    campaign_id: int,
    trigger_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Manually apply the trigger — enroll matching campaign contacts into the sequence."""
    trigger = db.query(CampaignSequenceTrigger).join(Campaign).filter(
        CampaignSequenceTrigger.id == trigger_id,
        CampaignSequenceTrigger.campaign_id == campaign_id,
        Campaign.company_id == current_user.company_id,
    ).first()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    contact_ids = _matching_contact_ids(db, campaign_id, trigger.trigger_condition)
    if not contact_ids:
        return {"enrolled": 0, "message": "No contacts matched this condition"}

    # Skip already-active/paused enrollments
    already = {
        r[0] for r in db.query(SequenceEnrollment.contact_id).filter(
            SequenceEnrollment.sequence_id == trigger.sequence_id,
            SequenceEnrollment.status.in_(["active", "paused"]),
        ).all()
    }

    enrolled = 0
    for contact_id in contact_ids:
        if contact_id in already:
            continue
        enrollment = SequenceEnrollment(
            sequence_id=trigger.sequence_id,
            contact_id=contact_id,
            enrolled_by_user_id=current_user.id,
        )
        db.add(enrollment)
        enrolled += 1

    trigger.last_fired_at = datetime.utcnow()
    trigger.enrolled_count = (trigger.enrolled_count or 0) + enrolled
    db.commit()

    return {
        "enrolled": enrolled,
        "skipped": len(contact_ids) - enrolled,
        "message": f"{enrolled} contact(s) enrolled into '{trigger.sequence.name}'",
    }


@router.get("/conditions")
def list_conditions():
    return [{"value": k, "label": v} for k, v in CONDITION_LABELS.items()]
