from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


class SequenceStepBase(BaseModel):
    step_order: int
    step_type: str = "email"
    template_id: Optional[int] = None
    delay_days: int = 0
    delay_hours: int = 0
    subject: Optional[str] = None
    body: Optional[str] = None
    condition: str = "always"
    task_note: Optional[str] = None


class SequenceStepCreate(SequenceStepBase):
    pass


class SequenceStepUpdate(BaseModel):
    step_order: Optional[int] = None
    step_type: Optional[str] = None
    template_id: Optional[int] = None
    delay_days: Optional[int] = None
    delay_hours: Optional[int] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    condition: Optional[str] = None
    task_note: Optional[str] = None


class SequenceStepTemplateInfo(BaseModel):
    id: int
    name: str
    template_type: str

    class Config:
        from_attributes = True


class SequenceStep(SequenceStepBase):
    id: int
    sequence_id: int
    template: Optional[SequenceStepTemplateInfo] = None

    class Config:
        from_attributes = True


class SequenceBase(BaseModel):
    name: str
    description: Optional[str] = None
    status: str = "draft"
    goal: Optional[str] = None
    tags: Optional[List[str]] = []


class SequenceCreate(SequenceBase):
    steps: Optional[List[SequenceStepCreate]] = []


class SequenceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    goal: Optional[str] = None
    tags: Optional[List[str]] = None
    steps: Optional[List[SequenceStepCreate]] = None


class SequenceContactInfo(BaseModel):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None

    class Config:
        from_attributes = True


class SequenceEnrollmentBase(BaseModel):
    contact_id: int


class SequenceEnrollmentCreate(BaseModel):
    contact_ids: List[int]


class SequenceEnrollment(BaseModel):
    id: int
    sequence_id: int
    contact_id: int
    status: str
    current_step: int
    enrolled_at: datetime
    next_send_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    contact: Optional[SequenceContactInfo] = None

    class Config:
        from_attributes = True


class SequenceStats(BaseModel):
    total_enrollments: int
    active: int
    completed: int
    paused: int
    failed: int


class Sequence(SequenceBase):
    id: int
    company_id: int
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    steps: List[SequenceStep] = []
    stats: Optional[SequenceStats] = None

    class Config:
        from_attributes = True


class SequenceList(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    status: str
    goal: Optional[str] = None
    tags: Optional[List[str]] = []
    created_at: datetime
    updated_at: datetime
    step_count: int = 0
    stats: Optional[SequenceStats] = None

    class Config:
        from_attributes = True
