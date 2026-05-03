from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


class TicketUserSummary(BaseModel):
    id: int
    full_name: Optional[str] = None
    email: Optional[str] = None

    class Config:
        from_attributes = True


class TicketContactSummary(BaseModel):
    id: int
    name: Optional[str] = None
    email: Optional[str] = None

    class Config:
        from_attributes = True


class TicketAccountSummary(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class TicketDealSummary(BaseModel):
    id: int
    title: str

    class Config:
        from_attributes = True


class TicketCreate(BaseModel):
    title: str
    description: Optional[str] = None
    status: Optional[str] = "open"
    priority: Optional[str] = "medium"
    contact_id: Optional[int] = None
    account_id: Optional[int] = None
    deal_id: Optional[int] = None
    assignee_id: Optional[int] = None
    tags: Optional[List[Any]] = []
    due_date: Optional[datetime] = None


class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    contact_id: Optional[int] = None
    account_id: Optional[int] = None
    deal_id: Optional[int] = None
    assignee_id: Optional[int] = None
    tags: Optional[List[Any]] = None
    due_date: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class TicketOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    status: str
    priority: str
    company_id: int
    contact_id: Optional[int] = None
    account_id: Optional[int] = None
    deal_id: Optional[int] = None
    assignee_id: Optional[int] = None
    created_by_user_id: Optional[int] = None
    tags: Optional[List[Any]] = []
    due_date: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    assignee: Optional[TicketUserSummary] = None
    contact: Optional[TicketContactSummary] = None
    account: Optional[TicketAccountSummary] = None
    deal: Optional[TicketDealSummary] = None
    comment_count: Optional[int] = 0

    class Config:
        from_attributes = True


class TicketCommentCreate(BaseModel):
    body: str
    is_internal: Optional[bool] = False


class TicketCommentOut(BaseModel):
    id: int
    ticket_id: int
    user_id: Optional[int] = None
    body: str
    is_internal: bool
    created_at: datetime
    user: Optional[TicketUserSummary] = None

    class Config:
        from_attributes = True


class TicketStatusUpdate(BaseModel):
    status: str


class TicketStats(BaseModel):
    by_status: dict
    by_priority: dict
