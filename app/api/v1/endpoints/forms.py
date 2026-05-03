from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional, Any, Dict
from pydantic import BaseModel
from datetime import datetime
import secrets
import re

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.models.form_builder import CaptureForm, FormSubmission
from app.models.contact import Contact

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class FormField(BaseModel):
    id: str
    type: str  # text, email, phone, textarea, select, checkbox, name
    label: str
    placeholder: Optional[str] = None
    required: bool = False
    options: Optional[List[str]] = None  # for select/radio
    width: str = "full"  # full, half


class FormSettings(BaseModel):
    submit_label: str = "Submit"
    submit_message: str = "Thank you! We'll be in touch."
    redirect_url: Optional[str] = None
    notify_email: Optional[str] = None
    create_contact: bool = True
    create_lead: bool = False
    primary_color: str = "#6366f1"
    bg_color: str = "#ffffff"
    font_family: str = "Inter"


class FormCreate(BaseModel):
    name: str
    description: Optional[str] = None
    fields: List[Dict[str, Any]] = []
    settings: Optional[Dict[str, Any]] = None


class FormUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    fields: Optional[List[Dict[str, Any]]] = None
    settings: Optional[Dict[str, Any]] = None


class FormOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    slug: str
    status: str
    fields: List[Dict[str, Any]]
    settings: Dict[str, Any]
    company_id: int
    created_at: datetime
    updated_at: datetime
    submission_count: int = 0

    class Config:
        from_attributes = True


class FormPublic(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    slug: str
    fields: List[Dict[str, Any]]
    settings: Dict[str, Any]

    class Config:
        from_attributes = True


class SubmissionOut(BaseModel):
    id: int
    form_id: int
    data: Dict[str, Any]
    contact_id: Optional[int] = None
    submitted_at: datetime

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_slug(name: str, db: Session) -> str:
    base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:40]
    slug = base
    suffix = 1
    while db.query(CaptureForm).filter(CaptureForm.slug == slug).first():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _upsert_contact(db: Session, company_id: int, data: dict) -> Optional[Contact]:
    email = data.get('email') or data.get('Email')
    name = (
        data.get('name') or data.get('Name') or
        f"{data.get('first_name', '')} {data.get('last_name', '')}".strip() or
        None
    )
    phone = data.get('phone') or data.get('phone_number') or data.get('Phone')
    company_name = data.get('company') or data.get('company_name') or data.get('Company')

    if not email and not name:
        return None

    contact = None
    if email:
        contact = db.query(Contact).filter(
            Contact.email == email, Contact.company_id == company_id
        ).first()

    if contact:
        if name and not contact.name:
            contact.name = name
        if phone and not contact.phone_number:
            contact.phone_number = phone
    else:
        contact = Contact(
            email=email,
            name=name,
            phone_number=phone,
            company_name=company_name,
            company_id=company_id,
            lead_source="form",
        )
        db.add(contact)
        db.flush()

    return contact


# ── Authenticated CRUD ────────────────────────────────────────────────────────

@router.get("/", response_model=List[FormOut])
def list_forms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    forms = db.query(CaptureForm).filter(
        CaptureForm.company_id == current_user.company_id
    ).order_by(CaptureForm.updated_at.desc()).all()

    result = []
    for f in forms:
        count = db.query(FormSubmission).filter(FormSubmission.form_id == f.id).count()
        out = FormOut.from_orm(f)
        out.submission_count = count
        result.append(out)
    return result


@router.post("/", response_model=FormOut)
def create_form(
    data: FormCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    slug = _make_slug(data.name, db)
    form = CaptureForm(
        name=data.name,
        description=data.description,
        company_id=current_user.company_id,
        slug=slug,
        fields=data.fields,
        settings=data.settings or {},
        created_by_user_id=current_user.id,
    )
    db.add(form)
    db.commit()
    db.refresh(form)
    out = FormOut.from_orm(form)
    out.submission_count = 0
    return out


@router.get("/{form_id}", response_model=FormOut)
def get_form(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    form = db.query(CaptureForm).filter(
        CaptureForm.id == form_id, CaptureForm.company_id == current_user.company_id
    ).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    count = db.query(FormSubmission).filter(FormSubmission.form_id == form_id).count()
    out = FormOut.from_orm(form)
    out.submission_count = count
    return out


@router.put("/{form_id}", response_model=FormOut)
def update_form(
    form_id: int,
    data: FormUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    form = db.query(CaptureForm).filter(
        CaptureForm.id == form_id, CaptureForm.company_id == current_user.company_id
    ).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    for field, value in data.dict(exclude_none=True).items():
        setattr(form, field, value)
    form.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(form)
    count = db.query(FormSubmission).filter(FormSubmission.form_id == form_id).count()
    out = FormOut.from_orm(form)
    out.submission_count = count
    return out


@router.delete("/{form_id}")
def delete_form(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    form = db.query(CaptureForm).filter(
        CaptureForm.id == form_id, CaptureForm.company_id == current_user.company_id
    ).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    db.delete(form)
    db.commit()
    return {"ok": True}


@router.get("/{form_id}/submissions", response_model=List[SubmissionOut])
def list_submissions(
    form_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    form = db.query(CaptureForm).filter(
        CaptureForm.id == form_id, CaptureForm.company_id == current_user.company_id
    ).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    return db.query(FormSubmission).filter(
        FormSubmission.form_id == form_id
    ).order_by(FormSubmission.submitted_at.desc()).offset(skip).limit(limit).all()


# ── Public endpoints (no auth) ────────────────────────────────────────────────

@router.get("/public/{slug}", response_model=FormPublic)
def get_public_form(slug: str, db: Session = Depends(get_db)):
    form = db.query(CaptureForm).filter(
        CaptureForm.slug == slug, CaptureForm.status == "active"
    ).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    return form


@router.post("/public/{slug}/submit")
def submit_form(
    slug: str,
    payload: Dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
):
    form = db.query(CaptureForm).filter(
        CaptureForm.slug == slug, CaptureForm.status == "active"
    ).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    settings = form.settings or {}
    contact_id = None

    if settings.get("create_contact", True):
        contact = _upsert_contact(db, form.company_id, payload)
        if contact:
            contact_id = contact.id

    ip = request.client.host if request.client else None
    submission = FormSubmission(
        form_id=form.id,
        data=payload,
        contact_id=contact_id,
        ip_address=ip,
    )
    db.add(submission)
    db.commit()

    return {
        "ok": True,
        "message": settings.get("submit_message", "Thank you! We'll be in touch."),
        "redirect_url": settings.get("redirect_url"),
    }
