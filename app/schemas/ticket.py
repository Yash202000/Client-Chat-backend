from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from datetime import datetime
from enum import Enum


# ── Enums ────────────────────────────────────────────────────────────────────

class TicketPriorityEnum(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"

class StatusCategoryEnum(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"

class TicketLinkTypeEnum(str, Enum):
    BLOCKS = "blocks"
    IS_BLOCKED_BY = "is_blocked_by"
    DUPLICATES = "duplicates"
    IS_DUPLICATED_BY = "is_duplicated_by"
    RELATES_TO = "relates_to"
    CLONES = "clones"


# ── Shared summaries ─────────────────────────────────────────────────────────

class UserSummary(BaseModel):
    id: int
    full_name: Optional[str] = None
    email: Optional[str] = None
    profile_picture_url: Optional[str] = None
    class Config: from_attributes = True

class StatusSummary(BaseModel):
    id: int
    name: str
    color: str
    category: StatusCategoryEnum
    position: int
    class Config: from_attributes = True

class IssueTypeSummary(BaseModel):
    id: int
    name: str
    icon: Optional[str] = None
    color: str
    class Config: from_attributes = True

class ProjectSummary(BaseModel):
    id: int
    name: str
    key: str
    color: Optional[str] = None
    icon: Optional[str] = None
    class Config: from_attributes = True

class TicketSummary(BaseModel):
    id: int
    ticket_number: str
    title: str
    priority: TicketPriorityEnum
    status: Optional[StatusSummary] = None
    issue_type: Optional[IssueTypeSummary] = None
    class Config: from_attributes = True


# ── Workflow schemas ──────────────────────────────────────────────────────────

class TicketStatusCreate(BaseModel):
    name: str
    color: str = "#6366f1"
    category: StatusCategoryEnum = StatusCategoryEnum.TODO
    position: int = 0
    is_default: bool = False

class TicketStatusUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    category: Optional[StatusCategoryEnum] = None
    position: Optional[int] = None
    is_default: Optional[bool] = None

class TicketStatusOut(BaseModel):
    id: int
    workflow_id: int
    company_id: int
    name: str
    color: str
    category: StatusCategoryEnum
    position: int
    is_default: bool
    created_at: datetime
    class Config: from_attributes = True

class ScreenField(BaseModel):
    field: str
    label: str
    required: bool = False

class PostActions(BaseModel):
    assign_to: Optional[Dict[str, Any]] = None  # {"type": "role"|"user"|"reporter"|"none", "value": ...}
    notify_watchers: bool = False

class TicketTransitionCreate(BaseModel):
    name: str
    from_status_id: Optional[int] = None
    to_status_id: int
    conditions: Optional[Dict[str, Any]] = None
    screen_fields: Optional[List[ScreenField]] = None
    post_actions: Optional[Dict[str, Any]] = None

class TicketTransitionUpdate(BaseModel):
    name: Optional[str] = None
    from_status_id: Optional[int] = None
    to_status_id: Optional[int] = None
    conditions: Optional[Dict[str, Any]] = None
    screen_fields: Optional[List[ScreenField]] = None
    post_actions: Optional[Dict[str, Any]] = None

class TicketTransitionOut(BaseModel):
    id: int
    workflow_id: int
    name: str
    from_status_id: Optional[int] = None
    to_status_id: int
    from_status: Optional[StatusSummary] = None
    to_status: Optional[StatusSummary] = None
    conditions: Optional[Dict[str, Any]] = None
    screen_fields: Optional[List[ScreenField]] = None
    post_actions: Optional[Dict[str, Any]] = None
    class Config: from_attributes = True

class TicketWorkflowCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_default: bool = False

class TicketWorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None

class TicketWorkflowOut(BaseModel):
    id: int
    company_id: int
    name: str
    description: Optional[str] = None
    is_default: bool
    entity_type: Optional[str] = None
    statuses: List[TicketStatusOut] = []
    transitions: List[TicketTransitionOut] = []
    created_at: datetime
    updated_at: datetime
    class Config: from_attributes = True


# ── Issue type schemas ────────────────────────────────────────────────────────

class TicketIssueTypeCreate(BaseModel):
    name: str
    icon: Optional[str] = None
    color: str = "#6366f1"
    description: Optional[str] = None
    is_default: bool = False
    position: int = 0

class TicketIssueTypeUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    position: Optional[int] = None

class TicketIssueTypeOut(BaseModel):
    id: int
    company_id: int
    name: str
    icon: Optional[str] = None
    color: str
    description: Optional[str] = None
    is_default: bool
    position: int
    created_at: datetime
    class Config: from_attributes = True


# ── Project schemas ───────────────────────────────────────────────────────────

class TicketProjectMemberOut(BaseModel):
    user_id: int
    role: str
    user: Optional[UserSummary] = None
    class Config: from_attributes = True

class TicketProjectCreate(BaseModel):
    name: str
    key: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: str = "#6366f1"
    default_workflow_id: Optional[int] = None

class TicketProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    default_workflow_id: Optional[int] = None

class TicketProjectOut(BaseModel):
    id: int
    company_id: int
    name: str
    key: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    default_workflow_id: Optional[int] = None
    ticket_counter: int
    open_ticket_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    default_workflow: Optional[TicketWorkflowOut] = None
    members: List[TicketProjectMemberOut] = []
    class Config: from_attributes = True


# ── Ticket schemas ────────────────────────────────────────────────────────────

class TicketCommentCreate(BaseModel):
    body: str
    is_internal: bool = False
    parent_id: Optional[int] = None

class TicketCommentUpdate(BaseModel):
    body: Optional[str] = None
    is_internal: Optional[bool] = None

class TicketCommentOut(BaseModel):
    id: int
    ticket_id: int
    author_id: int
    parent_id: Optional[int] = None
    body: str
    is_internal: bool
    created_at: datetime
    updated_at: datetime
    author: Optional[UserSummary] = None
    class Config: from_attributes = True

class TicketAttachmentOut(BaseModel):
    id: int
    ticket_id: int
    file_name: str
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    file_url: str
    created_at: datetime
    uploaded_by: Optional[UserSummary] = None
    class Config: from_attributes = True

class TicketActivityOut(BaseModel):
    id: int
    ticket_id: int
    action: str
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    metadata_: Optional[Dict[str, Any]] = None
    created_at: datetime
    actor: Optional[UserSummary] = None
    class Config:
        from_attributes = True
        populate_by_name = True

class TicketLinkOut(BaseModel):
    id: int
    source_ticket_id: int
    target_ticket_id: int
    link_type: TicketLinkTypeEnum
    source_ticket: Optional[TicketSummary] = None
    target_ticket: Optional[TicketSummary] = None
    class Config: from_attributes = True

class TicketCreate(BaseModel):
    project_id: int
    title: str
    description: Optional[str] = None
    issue_type_id: Optional[int] = None
    status_id: Optional[int] = None
    priority: TicketPriorityEnum = TicketPriorityEnum.MEDIUM
    assignee_id: Optional[int] = None
    parent_id: Optional[int] = None
    labels: Optional[List[str]] = None
    due_date: Optional[datetime] = None
    start_date: Optional[datetime] = None
    story_points: Optional[float] = None
    time_estimate: Optional[int] = None
    contact_id: Optional[int] = None
    account_id: Optional[int] = None
    deal_id: Optional[int] = None
    custom_fields: Optional[Dict[str, Any]] = None

class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    issue_type_id: Optional[int] = None
    status_id: Optional[int] = None
    priority: Optional[TicketPriorityEnum] = None
    assignee_id: Optional[int] = None
    parent_id: Optional[int] = None
    labels: Optional[List[str]] = None
    due_date: Optional[datetime] = None
    start_date: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    story_points: Optional[float] = None
    time_estimate: Optional[int] = None
    time_spent: Optional[int] = None
    contact_id: Optional[int] = None
    account_id: Optional[int] = None
    deal_id: Optional[int] = None
    custom_fields: Optional[Dict[str, Any]] = None
    position: Optional[float] = None

class TicketTransitionExecute(BaseModel):
    transition_id: int
    comment: Optional[str] = None
    field_values: Optional[Dict[str, Any]] = None

class TicketLinkCreate(BaseModel):
    target_ticket_id: int
    link_type: TicketLinkTypeEnum

class TicketOut(BaseModel):
    id: int
    company_id: int
    project_id: int
    ticket_number: str
    title: str
    description: Optional[str] = None
    priority: TicketPriorityEnum
    assignee_id: Optional[int] = None
    reporter_id: Optional[int] = None
    parent_id: Optional[int] = None
    labels: Optional[List[str]] = None
    due_date: Optional[datetime] = None
    start_date: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    story_points: Optional[float] = None
    time_estimate: Optional[int] = None
    time_spent: Optional[int] = None
    contact_id: Optional[int] = None
    account_id: Optional[int] = None
    deal_id: Optional[int] = None
    custom_fields: Optional[Dict[str, Any]] = None
    position: float
    created_at: datetime
    updated_at: datetime
    status: Optional[StatusSummary] = None
    issue_type: Optional[IssueTypeSummary] = None
    project: Optional[ProjectSummary] = None
    assignee: Optional[UserSummary] = None
    reporter: Optional[UserSummary] = None
    comment_count: Optional[int] = None
    attachment_count: Optional[int] = None
    class Config: from_attributes = True

class TicketDetailOut(TicketOut):
    comments: List[TicketCommentOut] = []
    attachments: List[TicketAttachmentOut] = []
    activities: List[TicketActivityOut] = []
    watchers: List[UserSummary] = []
    source_links: List[TicketLinkOut] = []
    target_links: List[TicketLinkOut] = []
    sub_tickets: List[TicketSummary] = []
    parent: Optional[TicketSummary] = None
    available_transitions: List[TicketTransitionOut] = []
    class Config: from_attributes = True


# ── Stats ─────────────────────────────────────────────────────────────────────

class TicketStats(BaseModel):
    total: int
    by_status: Dict[str, int]
    by_priority: Dict[str, int]
    by_issue_type: Dict[str, int]
    open_count: int
    resolved_count: int
    overdue_count: int


# ── Sprint schemas ────────────────────────────────────────────────────────────

class SprintStatusEnum(str, Enum):
    FUTURE = "future"
    ACTIVE = "active"
    COMPLETED = "completed"

class TicketSprintCreate(BaseModel):
    name: str
    goal: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

class TicketSprintUpdate(BaseModel):
    name: Optional[str] = None
    goal: Optional[str] = None
    status: Optional[SprintStatusEnum] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

class TicketSprintOut(BaseModel):
    id: int
    project_id: int
    company_id: int
    name: str
    goal: Optional[str] = None
    status: SprintStatusEnum
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    ticket_count: Optional[int] = None
    completed_count: Optional[int] = None
    class Config: from_attributes = True
