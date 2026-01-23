from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timedelta
from app.models.content_item import ContentItem
from app.models.content_type import ContentType
from app.models.content_publishing import ContentExport
from app.schemas.cms import ContentStatus, ContentVisibility
from app.core.object_storage import s3_client, BUCKET_NAME
import json
import csv
import io


def create_export_request(
    db: Session,
    company_id: int,
    user_id: int,
    export_format: str,
    knowledge_base_id: Optional[int] = None,
    content_type_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    visibility_filter: Optional[str] = None
) -> ContentExport:
    """Create an export request record."""
    if export_format not in ['json', 'csv']:
        raise ValueError("Export format must be 'json' or 'csv'")

    # Build filter criteria for tracking
    filter_criteria = {
        "knowledge_base_id": knowledge_base_id,
        "content_type_id": content_type_id,
        "status": status_filter,
        "visibility": visibility_filter
    }

    export_record = ContentExport(
        company_id=company_id,
        knowledge_base_id=knowledge_base_id,
        format=export_format,
        status='pending',
        filter_criteria=json.dumps(filter_criteria),
        requested_by=user_id,
        expires_at=datetime.utcnow() + timedelta(days=7)  # Expire in 7 days
    )

    db.add(export_record)
    db.commit()
    db.refresh(export_record)

    return export_record


def get_export(db: Session, export_id: int, company_id: int) -> Optional[ContentExport]:
    """Get an export record by ID."""
    return db.query(ContentExport).filter(
        and_(
            ContentExport.id == export_id,
            ContentExport.company_id == company_id
        )
    ).first()


def get_exports(
    db: Session,
    company_id: int,
    skip: int = 0,
    limit: int = 50
) -> List[ContentExport]:
    """Get export history for a company."""
    return db.query(ContentExport).filter(
        ContentExport.company_id == company_id
    ).order_by(ContentExport.created_at.desc()).offset(skip).limit(limit).all()


def process_export(db: Session, export_id: int, company_id: int) -> ContentExport:
    """
    Process an export request - generates the export file and uploads to S3.
    This should typically be run as a background task.
    """
    export_record = get_export(db, export_id, company_id)
    if not export_record:
        raise ValueError("Export not found")

    if export_record.status != 'pending':
        raise ValueError(f"Export is already {export_record.status}")

    # Update status to processing
    export_record.status = 'processing'
    db.commit()

    try:
        # Parse filter criteria
        filters = json.loads(export_record.filter_criteria) if export_record.filter_criteria else {}

        # Query content items
        query = db.query(ContentItem).filter(ContentItem.company_id == company_id)

        if filters.get('knowledge_base_id'):
            query = query.filter(ContentItem.knowledge_base_id == filters['knowledge_base_id'])
        if filters.get('content_type_id'):
            query = query.filter(ContentItem.content_type_id == filters['content_type_id'])
        if filters.get('status'):
            query = query.filter(ContentItem.status == filters['status'])
        if filters.get('visibility'):
            query = query.filter(ContentItem.visibility == filters['visibility'])

        items = query.order_by(ContentItem.created_at.desc()).all()

        # Generate export content
        if export_record.format == 'json':
            content, file_size = _generate_json_export(db, items)
            content_type = 'application/json'
            file_ext = 'json'
        else:  # csv
            content, file_size = _generate_csv_export(db, items)
            content_type = 'text/csv'
            file_ext = 'csv'

        # Upload to S3
        s3_key = f"exports/{company_id}/{export_id}/export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.{file_ext}"

        s3_client.put_object(
            Body=content.encode('utf-8'),
            Bucket=BUCKET_NAME,
            Key=s3_key,
            ContentType=content_type
        )

        # Update export record
        export_record.status = 'completed'
        export_record.s3_key = s3_key
        export_record.file_size = file_size
        export_record.item_count = len(items)
        export_record.completed_at = datetime.utcnow()

        db.commit()
        db.refresh(export_record)

        return export_record

    except Exception as e:
        export_record.status = 'failed'
        db.commit()
        raise ValueError(f"Export failed: {str(e)}")


def _generate_json_export(db: Session, items: List[ContentItem]) -> tuple[str, int]:
    """Generate JSON export content."""
    export_data = []

    for item in items:
        # Get content type info
        content_type = db.query(ContentType).filter(
            ContentType.id == item.content_type_id
        ).first()

        item_data = {
            "id": item.id,
            "content_type": {
                "id": content_type.id if content_type else None,
                "slug": content_type.slug if content_type else None,
                "name": content_type.name if content_type else None
            },
            "data": item.data,
            "status": item.status,
            "visibility": item.visibility,
            "version": item.version,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "published_at": item.published_at.isoformat() if item.published_at else None
        }
        export_data.append(item_data)

    content = json.dumps({
        "exported_at": datetime.utcnow().isoformat(),
        "item_count": len(export_data),
        "items": export_data
    }, indent=2, ensure_ascii=False)

    return content, len(content.encode('utf-8'))


def _generate_csv_export(db: Session, items: List[ContentItem]) -> tuple[str, int]:
    """Generate CSV export content."""
    if not items:
        return "No items to export", 0

    output = io.StringIO()

    # Collect all unique field keys from all items
    all_keys = set()
    for item in items:
        if item.data:
            all_keys.update(item.data.keys())

    # Sort keys for consistent column order
    field_keys = sorted(all_keys)

    # Define CSV columns
    base_columns = ['id', 'content_type_slug', 'status', 'visibility', 'version', 'created_at', 'updated_at', 'published_at']
    all_columns = base_columns + [f"data.{k}" for k in field_keys]

    writer = csv.DictWriter(output, fieldnames=all_columns)
    writer.writeheader()

    for item in items:
        content_type = db.query(ContentType).filter(
            ContentType.id == item.content_type_id
        ).first()

        row = {
            'id': item.id,
            'content_type_slug': content_type.slug if content_type else '',
            'status': item.status,
            'visibility': item.visibility,
            'version': item.version,
            'created_at': item.created_at.isoformat() if item.created_at else '',
            'updated_at': item.updated_at.isoformat() if item.updated_at else '',
            'published_at': item.published_at.isoformat() if item.published_at else ''
        }

        # Add data fields
        for key in field_keys:
            value = item.data.get(key, '') if item.data else ''
            # Convert complex values to JSON string
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            row[f"data.{key}"] = value

        writer.writerow(row)

    content = output.getvalue()
    return content, len(content.encode('utf-8'))


def get_export_download_url(db: Session, export_id: int, company_id: int, expires_in: int = 3600) -> Optional[str]:
    """Generate a pre-signed URL for downloading an export."""
    export_record = get_export(db, export_id, company_id)
    if not export_record or not export_record.s3_key:
        return None

    if export_record.status != 'completed':
        return None

    try:
        return s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': BUCKET_NAME, 'Key': export_record.s3_key},
            ExpiresIn=expires_in
        )
    except Exception as e:
        print(f"Error generating export download URL: {e}")
        return None


def delete_export(db: Session, export_id: int, company_id: int) -> bool:
    """Delete an export record and its file from S3."""
    export_record = get_export(db, export_id, company_id)
    if not export_record:
        return False

    # Delete from S3 if exists
    if export_record.s3_key:
        try:
            s3_client.delete_object(Bucket=BUCKET_NAME, Key=export_record.s3_key)
        except Exception as e:
            print(f"Error deleting export file from S3: {e}")

    db.delete(export_record)
    db.commit()

    return True


def cleanup_expired_exports(db: Session) -> int:
    """Delete expired exports. Returns count of deleted exports."""
    expired = db.query(ContentExport).filter(
        and_(
            ContentExport.expires_at < datetime.utcnow(),
            ContentExport.expires_at.isnot(None)
        )
    ).all()

    count = 0
    for export_record in expired:
        if export_record.s3_key:
            try:
                s3_client.delete_object(Bucket=BUCKET_NAME, Key=export_record.s3_key)
            except Exception:
                pass
        db.delete(export_record)
        count += 1

    db.commit()
    return count


def export_content_immediate(
    db: Session,
    company_id: int,
    user_id: int,
    export_format: str,
    knowledge_base_id: Optional[int] = None,
    content_type_id: Optional[int] = None,
    status_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Export content immediately and return the data directly.
    For smaller exports where we don't need async processing.
    """
    # Query content items
    query = db.query(ContentItem).filter(ContentItem.company_id == company_id)

    if knowledge_base_id:
        query = query.filter(ContentItem.knowledge_base_id == knowledge_base_id)
    if content_type_id:
        query = query.filter(ContentItem.content_type_id == content_type_id)
    if status_filter:
        query = query.filter(ContentItem.status == status_filter)

    items = query.order_by(ContentItem.created_at.desc()).all()

    if export_format == 'json':
        content, file_size = _generate_json_export(db, items)
        return {
            "format": "json",
            "content": json.loads(content),
            "item_count": len(items)
        }
    else:  # csv
        content, file_size = _generate_csv_export(db, items)
        return {
            "format": "csv",
            "content": content,
            "item_count": len(items)
        }
