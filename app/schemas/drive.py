from pydantic import BaseModel, ConfigDict
from typing import List, Optional
import datetime


class DriveItemResponse(BaseModel):
    id: int
    company_id: int
    owner_id: Optional[int] = None
    parent_id: Optional[int] = None
    name: str
    is_folder: bool
    s3_key: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    owner_name: Optional[str] = None
    download_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DriveItemCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None


class DriveItemUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None


class DriveListResponse(BaseModel):
    items: List[DriveItemResponse]
    total_count: int


class DriveStatsResponse(BaseModel):
    total_bytes: int
    file_count: int
    folder_count: int
