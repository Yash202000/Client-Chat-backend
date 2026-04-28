from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta

from app.schemas.drive import (
    DriveItemResponse, DriveItemCreate, DriveItemUpdate,
    DriveListResponse, DriveStatsResponse,
)
from app.services import drive_service
from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User

router = APIRouter()


def _to_response(item, owner_name: Optional[str] = None, download_url: Optional[str] = None) -> DriveItemResponse:
    resp = DriveItemResponse.model_validate(item)
    if owner_name:
        resp.owner_name = owner_name
    if download_url:
        resp.download_url = download_url
    return resp


def _enrich(item, download_url=None) -> DriveItemResponse:
    owner_name = None
    if item.owner:
        owner_name = item.owner.first_name or item.owner.email
    return _to_response(item, owner_name=owner_name, download_url=download_url)


@router.get("/items", response_model=DriveListResponse)
def list_items(
    parent_id: Optional[int] = Query(None),
    sort_by:   str           = Query("name", regex="^(name|date|size)$"),
    sort_dir:  str           = Query("asc",  regex="^(asc|desc)$"),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_active_user),
):
    items = drive_service.list_folder(db, current_user.company_id, parent_id, sort_by, sort_dir)
    return DriveListResponse(items=[_enrich(i) for i in items], total_count=len(items))


@router.post("/folders", response_model=DriveItemResponse, status_code=201)
def create_folder(
    body:         DriveItemCreate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_active_user),
):
    item = drive_service.create_folder(db, current_user.company_id, current_user.id, body.name, body.parent_id)
    return _enrich(item)


@router.post("/files", response_model=DriveItemResponse, status_code=201)
async def upload_file(
    file:         UploadFile       = File(...),
    parent_id:    Optional[int]    = Form(None),
    db:           Session          = Depends(get_db),
    current_user: User             = Depends(get_current_active_user),
):
    item = await drive_service.upload_file(db, file, current_user.company_id, current_user.id, parent_id)
    return _enrich(item)


@router.patch("/items/{item_id}", response_model=DriveItemResponse)
def update_item(
    item_id:      int,
    body:         DriveItemUpdate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_active_user),
):
    item = drive_service.get_item(db, item_id, current_user.company_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if body.name is not None:
        item = drive_service.rename_item(db, item_id, current_user.company_id, body.name)
    if body.parent_id is not None or (body.model_fields_set and 'parent_id' in body.model_fields_set):
        item = drive_service.move_item(db, item.id, current_user.company_id, body.parent_id)
    return _enrich(item)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(
    item_id:      int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_active_user),
):
    drive_service.delete_item(db, item_id, current_user.company_id)


@router.get("/items/{item_id}/download-url")
def get_download_url(
    item_id:    int,
    expires_in: int     = Query(3600, ge=60, le=86400),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_active_user),
):
    item = drive_service.get_item(db, item_id, current_user.company_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    url = drive_service.get_presigned_url(item, expires_in)
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    return {"url": url, "expires_at": expires_at.isoformat()}


@router.get("/items/{item_id}/breadcrumb", response_model=List[DriveItemResponse])
def get_breadcrumb(
    item_id:      int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_active_user),
):
    path = drive_service.get_breadcrumb(db, item_id, current_user.company_id)
    return [_enrich(i) for i in path]


@router.get("/search", response_model=DriveListResponse)
def search(
    q:     str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_active_user),
):
    items = drive_service.search_items(db, current_user.company_id, q, limit)
    return DriveListResponse(items=[_enrich(i) for i in items], total_count=len(items))


@router.get("/stats", response_model=DriveStatsResponse)
def get_stats(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_active_user),
):
    return drive_service.get_storage_stats(db, current_user.company_id)
