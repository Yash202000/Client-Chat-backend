from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func
from typing import List, Optional

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.models.sequence import Sequence, SequenceStep, SequenceEnrollment, SequenceStepLog
from app.schemas.sequence import (
    SequenceCreate, SequenceUpdate, Sequence as SequenceSchema, SequenceList,
    SequenceStep as SequenceStepSchema, SequenceStepCreate, SequenceStepUpdate,
    SequenceEnrollment as SequenceEnrollmentSchema, SequenceEnrollmentCreate,
    SequenceStats,
)
from datetime import datetime

router = APIRouter()


def _build_stats(db: Session, sequence_id: int) -> SequenceStats:
    rows = (
        db.query(SequenceEnrollment.status, func.count(SequenceEnrollment.id))
        .filter(SequenceEnrollment.sequence_id == sequence_id)
        .group_by(SequenceEnrollment.status)
        .all()
    )
    counts = {r[0]: r[1] for r in rows}
    total = sum(counts.values())
    return SequenceStats(
        total_enrollments=total,
        active=counts.get("active", 0),
        completed=counts.get("completed", 0),
        paused=counts.get("paused", 0),
        failed=counts.get("failed", 0),
    )


# ── Sequences CRUD ────────────────────────────────────────────────────────────

@router.get("/", response_model=List[SequenceList])
def list_sequences(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    q = db.query(Sequence).filter(Sequence.company_id == current_user.company_id)
    if status:
        q = q.filter(Sequence.status == status)
    sequences = q.order_by(Sequence.updated_at.desc()).offset(skip).limit(limit).all()

    result = []
    for s in sequences:
        step_count = db.query(func.count(SequenceStep.id)).filter(SequenceStep.sequence_id == s.id).scalar()
        result.append(SequenceList(
            id=s.id,
            name=s.name,
            description=s.description,
            status=s.status,
            goal=s.goal,
            tags=s.tags or [],
            created_at=s.created_at,
            updated_at=s.updated_at,
            step_count=step_count,
            stats=_build_stats(db, s.id),
        ))
    return result


@router.post("/", response_model=SequenceSchema)
def create_sequence(
    data: SequenceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    seq = Sequence(
        name=data.name,
        description=data.description,
        company_id=current_user.company_id,
        status=data.status,
        goal=data.goal,
        tags=data.tags or [],
        created_by_user_id=current_user.id,
    )
    db.add(seq)
    db.flush()

    for step_data in (data.steps or []):
        step = SequenceStep(sequence_id=seq.id, **step_data.dict())
        db.add(step)

    db.commit()
    db.refresh(seq)
    seq_out = SequenceSchema.from_orm(seq)
    seq_out.stats = _build_stats(db, seq.id)
    return seq_out


@router.get("/{sequence_id}", response_model=SequenceSchema)
def get_sequence(
    sequence_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    seq = (
        db.query(Sequence)
        .options(selectinload(Sequence.steps).joinedload(SequenceStep.template))
        .filter(Sequence.id == sequence_id, Sequence.company_id == current_user.company_id)
        .first()
    )
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    seq_out = SequenceSchema.from_orm(seq)
    seq_out.stats = _build_stats(db, seq.id)
    return seq_out


@router.put("/{sequence_id}", response_model=SequenceSchema)
def update_sequence(
    sequence_id: int,
    data: SequenceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    seq = db.query(Sequence).filter(
        Sequence.id == sequence_id, Sequence.company_id == current_user.company_id
    ).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")

    for field, value in data.dict(exclude_none=True, exclude={"steps"}).items():
        setattr(seq, field, value)
    seq.updated_at = datetime.utcnow()

    if data.steps is not None:
        db.query(SequenceStep).filter(SequenceStep.sequence_id == seq.id).delete()
        for step_data in data.steps:
            step = SequenceStep(sequence_id=seq.id, **step_data.dict())
            db.add(step)

    db.commit()
    db.refresh(seq)
    seq_out = SequenceSchema.from_orm(seq)
    seq_out.stats = _build_stats(db, seq.id)
    return seq_out


@router.delete("/{sequence_id}")
def delete_sequence(
    sequence_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    seq = db.query(Sequence).filter(
        Sequence.id == sequence_id, Sequence.company_id == current_user.company_id
    ).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    db.delete(seq)
    db.commit()
    return {"ok": True}


# ── Steps ─────────────────────────────────────────────────────────────────────

@router.post("/{sequence_id}/steps", response_model=SequenceStepSchema)
def add_step(
    sequence_id: int,
    data: SequenceStepCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    seq = db.query(Sequence).filter(
        Sequence.id == sequence_id, Sequence.company_id == current_user.company_id
    ).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    step = SequenceStep(sequence_id=sequence_id, **data.dict())
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


@router.put("/{sequence_id}/steps/{step_id}", response_model=SequenceStepSchema)
def update_step(
    sequence_id: int,
    step_id: int,
    data: SequenceStepUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    step = db.query(SequenceStep).join(Sequence).filter(
        SequenceStep.id == step_id,
        SequenceStep.sequence_id == sequence_id,
        Sequence.company_id == current_user.company_id,
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    for field, value in data.dict(exclude_none=True).items():
        setattr(step, field, value)
    db.commit()
    db.refresh(step)
    return step


@router.delete("/{sequence_id}/steps/{step_id}")
def delete_step(
    sequence_id: int,
    step_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    step = db.query(SequenceStep).join(Sequence).filter(
        SequenceStep.id == step_id,
        SequenceStep.sequence_id == sequence_id,
        Sequence.company_id == current_user.company_id,
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    db.delete(step)
    db.commit()
    return {"ok": True}


# ── Enrollments ───────────────────────────────────────────────────────────────

@router.get("/{sequence_id}/enrollments", response_model=List[SequenceEnrollmentSchema])
def list_enrollments(
    sequence_id: int,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    seq = db.query(Sequence).filter(
        Sequence.id == sequence_id, Sequence.company_id == current_user.company_id
    ).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")

    q = (
        db.query(SequenceEnrollment)
        .options(joinedload(SequenceEnrollment.contact))
        .filter(SequenceEnrollment.sequence_id == sequence_id)
    )
    if status:
        q = q.filter(SequenceEnrollment.status == status)
    return q.order_by(SequenceEnrollment.enrolled_at.desc()).offset(skip).limit(limit).all()


@router.post("/{sequence_id}/enroll", response_model=List[SequenceEnrollmentSchema])
def enroll_contacts(
    sequence_id: int,
    data: SequenceEnrollmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    seq = db.query(Sequence).filter(
        Sequence.id == sequence_id, Sequence.company_id == current_user.company_id
    ).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")

    existing_ids = {
        r[0] for r in db.query(SequenceEnrollment.contact_id).filter(
            SequenceEnrollment.sequence_id == sequence_id,
            SequenceEnrollment.status.in_(["active", "paused"]),
        ).all()
    }

    created = []
    for contact_id in data.contact_ids:
        if contact_id in existing_ids:
            continue
        enrollment = SequenceEnrollment(
            sequence_id=sequence_id,
            contact_id=contact_id,
            enrolled_by_user_id=current_user.id,
        )
        db.add(enrollment)
        created.append(enrollment)

    db.commit()
    for e in created:
        db.refresh(e)
    return created


@router.patch("/{sequence_id}/enrollments/{enrollment_id}")
def update_enrollment_status(
    sequence_id: int,
    enrollment_id: int,
    status: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    enrollment = db.query(SequenceEnrollment).join(Sequence).filter(
        SequenceEnrollment.id == enrollment_id,
        SequenceEnrollment.sequence_id == sequence_id,
        Sequence.company_id == current_user.company_id,
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    enrollment.status = status
    if status == "completed":
        enrollment.completed_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.delete("/{sequence_id}/enrollments/{enrollment_id}")
def unenroll_contact(
    sequence_id: int,
    enrollment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    enrollment = db.query(SequenceEnrollment).join(Sequence).filter(
        SequenceEnrollment.id == enrollment_id,
        SequenceEnrollment.sequence_id == sequence_id,
        Sequence.company_id == current_user.company_id,
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    db.delete(enrollment)
    db.commit()
    return {"ok": True}
