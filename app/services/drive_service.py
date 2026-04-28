from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from fastapi import UploadFile, HTTPException
from app.models.drive_item import DriveItem
from app.core.object_storage import s3_client, BUCKET_NAME
import uuid
import re


MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB per file


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[^\w\s\-.]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    return name[:200] or 'file'


def _build_s3_key(company_id: int, filename: str) -> str:
    safe = _sanitize_filename(filename)
    return f"drive/{company_id}/{uuid.uuid4()}_{safe}"


def get_item(db: Session, item_id: int, company_id: int) -> Optional[DriveItem]:
    return db.query(DriveItem).filter(
        DriveItem.id == item_id,
        DriveItem.company_id == company_id,
    ).first()


def list_folder(
    db: Session,
    company_id: int,
    parent_id: Optional[int],
    sort_by: str = "name",
    sort_dir: str = "asc",
) -> List[DriveItem]:
    sort_col = {
        "name": DriveItem.name,
        "date": DriveItem.created_at,
        "size": DriveItem.file_size,
    }.get(sort_by, DriveItem.name)

    order = sort_col.asc() if sort_dir == "asc" else sort_col.desc()

    return (
        db.query(DriveItem)
        .filter(
            DriveItem.company_id == company_id,
            DriveItem.parent_id == parent_id,
        )
        .order_by(DriveItem.is_folder.desc(), order)
        .all()
    )


def create_folder(
    db: Session,
    company_id: int,
    owner_id: int,
    name: str,
    parent_id: Optional[int] = None,
) -> DriveItem:
    if parent_id is not None:
        parent = get_item(db, parent_id, company_id)
        if not parent or not parent.is_folder:
            raise HTTPException(status_code=400, detail="Parent folder not found")

    item = DriveItem(
        company_id=company_id,
        owner_id=owner_id,
        parent_id=parent_id,
        name=name,
        is_folder=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


async def upload_file(
    db: Session,
    file: UploadFile,
    company_id: int,
    owner_id: int,
    parent_id: Optional[int] = None,
) -> DriveItem:
    if parent_id is not None:
        parent = get_item(db, parent_id, company_id)
        if not parent or not parent.is_folder:
            raise HTTPException(status_code=400, detail="Parent folder not found")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 500 MB)")

    s3_key = _build_s3_key(company_id, file.filename or "upload")
    mime = file.content_type or "application/octet-stream"

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=s3_key,
        Body=content,
        ContentType=mime,
    )

    item = DriveItem(
        company_id=company_id,
        owner_id=owner_id,
        parent_id=parent_id,
        name=file.filename or "upload",
        is_folder=False,
        s3_key=s3_key,
        mime_type=mime,
        file_size=len(content),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def rename_item(db: Session, item_id: int, company_id: int, new_name: str) -> DriveItem:
    item = get_item(db, item_id, company_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.name = new_name
    db.commit()
    db.refresh(item)
    return item


def move_item(db: Session, item_id: int, company_id: int, new_parent_id: Optional[int]) -> DriveItem:
    item = get_item(db, item_id, company_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if new_parent_id is not None:
        target = get_item(db, new_parent_id, company_id)
        if not target or not target.is_folder:
            raise HTTPException(status_code=400, detail="Target folder not found")
        # Guard against circular reference
        cursor_id: Optional[int] = new_parent_id
        while cursor_id is not None:
            if cursor_id == item_id:
                raise HTTPException(status_code=400, detail="Cannot move a folder into itself")
            cursor = db.query(DriveItem.parent_id).filter(DriveItem.id == cursor_id).scalar()
            cursor_id = cursor

    item.parent_id = new_parent_id
    db.commit()
    db.refresh(item)
    return item


def _collect_descendant_keys(db: Session, folder_id: int) -> List[str]:
    """Recursive CTE to collect all s3_keys under a folder."""
    result = db.execute(text("""
        WITH RECURSIVE descendants AS (
            SELECT id, s3_key, is_folder
            FROM drive_items
            WHERE id = :root_id
            UNION ALL
            SELECT di.id, di.s3_key, di.is_folder
            FROM drive_items di
            JOIN descendants d ON di.parent_id = d.id
        )
        SELECT s3_key FROM descendants WHERE s3_key IS NOT NULL
    """), {"root_id": folder_id})
    return [row[0] for row in result]


def delete_item(db: Session, item_id: int, company_id: int) -> None:
    item = get_item(db, item_id, company_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if item.is_folder:
        keys = _collect_descendant_keys(db, item_id)
    else:
        keys = [item.s3_key] if item.s3_key else []

    # Batch-delete from S3 (max 1000 per call)
    for i in range(0, len(keys), 1000):
        batch = keys[i:i + 1000]
        s3_client.delete_objects(
            Bucket=BUCKET_NAME,
            Delete={"Objects": [{"Key": k} for k in batch]},
        )

    db.delete(item)
    db.commit()


def get_presigned_url(item: DriveItem, expires_in: int = 3600) -> str:
    if not item.s3_key:
        raise HTTPException(status_code=400, detail="Item has no associated file")
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET_NAME, "Key": item.s3_key},
        ExpiresIn=expires_in,
    )


def search_items(db: Session, company_id: int, query: str, limit: int = 50) -> List[DriveItem]:
    return (
        db.query(DriveItem)
        .filter(
            DriveItem.company_id == company_id,
            DriveItem.is_folder == False,
            DriveItem.name.ilike(f"%{query}%"),
        )
        .order_by(DriveItem.name)
        .limit(limit)
        .all()
    )


def get_storage_stats(db: Session, company_id: int) -> dict:
    row = db.query(
        func.coalesce(func.sum(DriveItem.file_size), 0).label("total_bytes"),
        func.count().filter(DriveItem.is_folder == False).label("file_count"),
        func.count().filter(DriveItem.is_folder == True).label("folder_count"),
    ).filter(DriveItem.company_id == company_id).one()
    return {
        "total_bytes": row.total_bytes,
        "file_count": row.file_count,
        "folder_count": row.folder_count,
    }


def get_breadcrumb(db: Session, item_id: int, company_id: int) -> List[DriveItem]:
    """Return ordered list from root down to the given item."""
    path = []
    cursor_id: Optional[int] = item_id
    while cursor_id is not None:
        item = get_item(db, cursor_id, company_id)
        if not item:
            break
        path.append(item)
        cursor_id = item.parent_id
    path.reverse()
    return path
