from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class DealStageBase(BaseModel):
    name: str
    position: int = 0
    probability: int = 0
    color: Optional[str] = "#6366f1"


class DealStageCreate(DealStageBase):
    pass


class DealStageUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[int] = None
    probability: Optional[int] = None
    color: Optional[str] = None


class DealStage(DealStageBase):
    id: int
    pipeline_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PipelineBase(BaseModel):
    name: str
    is_default: bool = False


class PipelineCreate(PipelineBase):
    stages: Optional[List[DealStageCreate]] = []


class PipelineUpdate(BaseModel):
    name: Optional[str] = None
    is_default: Optional[bool] = None


class Pipeline(PipelineBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: datetime
    stages: List[DealStage] = []

    class Config:
        from_attributes = True
