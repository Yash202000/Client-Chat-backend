from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.schemas.cms import ContentMediaResponse, ContentMediaUpdate
from app.services.cms import media_service
from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user

router = APIRouter()


class MediaListResponse(BaseModel):
    items: List[ContentMediaResponse]
    total: int


class MediaUploadResponse(ContentMediaResponse):
    url: str
    thumbnail_url: Optional[str] = None


@router.post("/upload", response_model=MediaUploadResponse)
async def upload_media(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    file: UploadFile = File(...),
    alt_text: Optional[str] = Form(None),
    caption: Optional[str] = Form(None)
):
    """
    Upload a media file (image, audio, video, or document).

    Supported formats:
    - **Images**: jpg, jpeg, png, gif, webp, svg (max 10 MB)
    - **Audio**: mp3, wav, ogg, webm, aac, m4a (max 50 MB)
    - **Video**: mp4, webm, ogg, mov (max 200 MB)
    - **Files**: pdf, doc, docx, xls, xlsx, txt, csv (max 25 MB)

    For images, a thumbnail is automatically generated.
    For audio/video, duration is automatically extracted.
    """
    try:
        db_media = await media_service.upload_media(
            db=db,
            file=file,
            company_id=current_user.company_id,
            user_id=current_user.id,
            alt_text=alt_text,
            caption=caption
        )

        # Get URLs
        url = media_service.get_media_url(db_media)
        thumbnail_url = media_service.get_thumbnail_url(db_media)

        # Build response
        response = MediaUploadResponse(
            id=db_media.id,
            company_id=db_media.company_id,
            filename=db_media.filename,
            original_filename=db_media.original_filename,
            mime_type=db_media.mime_type,
            file_size=db_media.file_size,
            media_type=db_media.media_type,
            s3_bucket=db_media.s3_bucket,
            s3_key=db_media.s3_key,
            thumbnail_s3_key=db_media.thumbnail_s3_key,
            width=db_media.width,
            height=db_media.height,
            duration=db_media.duration,
            alt_text=db_media.alt_text,
            caption=db_media.caption,
            usage_count=db_media.usage_count,
            uploaded_by=db_media.uploaded_by,
            created_at=db_media.created_at,
            url=url,
            thumbnail_url=thumbnail_url
        )

        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=MediaListResponse)
def list_media(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    media_type: Optional[str] = Query(None, description="Filter by media type (image, audio, video, file)"),
    search: Optional[str] = Query(None, description="Search by filename or alt text"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200)
):
    """
    List all media files for the current company.
    """
    items = media_service.get_content_media_list(
        db=db,
        company_id=current_user.company_id,
        media_type=media_type,
        search=search,
        skip=skip,
        limit=limit
    )

    total = media_service.get_content_media_count(
        db=db,
        company_id=current_user.company_id,
        media_type=media_type
    )

    # Add URLs to each item
    items_with_urls = []
    for item in items:
        item_dict = {
            "id": item.id,
            "company_id": item.company_id,
            "filename": item.filename,
            "original_filename": item.original_filename,
            "mime_type": item.mime_type,
            "file_size": item.file_size,
            "media_type": item.media_type,
            "s3_bucket": item.s3_bucket,
            "s3_key": item.s3_key,
            "thumbnail_s3_key": item.thumbnail_s3_key,
            "width": item.width,
            "height": item.height,
            "duration": item.duration,
            "alt_text": item.alt_text,
            "caption": item.caption,
            "usage_count": item.usage_count,
            "uploaded_by": item.uploaded_by,
            "created_at": item.created_at,
            "url": media_service.get_media_url(item)
        }
        items_with_urls.append(ContentMediaResponse(**item_dict))

    return MediaListResponse(items=items_with_urls, total=total)


@router.get("/{media_id}", response_model=ContentMediaResponse)
def get_media(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    media_id: int
):
    """
    Get a single media item by ID.
    """
    media = media_service.get_content_media(
        db=db,
        media_id=media_id,
        company_id=current_user.company_id
    )
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    # Add URL
    response = ContentMediaResponse(
        id=media.id,
        company_id=media.company_id,
        filename=media.filename,
        original_filename=media.original_filename,
        mime_type=media.mime_type,
        file_size=media.file_size,
        media_type=media.media_type,
        s3_bucket=media.s3_bucket,
        s3_key=media.s3_key,
        thumbnail_s3_key=media.thumbnail_s3_key,
        width=media.width,
        height=media.height,
        duration=media.duration,
        alt_text=media.alt_text,
        caption=media.caption,
        usage_count=media.usage_count,
        uploaded_by=media.uploaded_by,
        created_at=media.created_at,
        url=media_service.get_media_url(media)
    )

    return response


@router.put("/{media_id}", response_model=ContentMediaResponse)
def update_media(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    media_id: int,
    media_update: ContentMediaUpdate
):
    """
    Update media metadata (alt text and caption).
    """
    media = media_service.update_media(
        db=db,
        media_id=media_id,
        company_id=current_user.company_id,
        alt_text=media_update.alt_text,
        caption=media_update.caption
    )
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    # Add URL
    response = ContentMediaResponse(
        id=media.id,
        company_id=media.company_id,
        filename=media.filename,
        original_filename=media.original_filename,
        mime_type=media.mime_type,
        file_size=media.file_size,
        media_type=media.media_type,
        s3_bucket=media.s3_bucket,
        s3_key=media.s3_key,
        thumbnail_s3_key=media.thumbnail_s3_key,
        width=media.width,
        height=media.height,
        duration=media.duration,
        alt_text=media.alt_text,
        caption=media.caption,
        usage_count=media.usage_count,
        uploaded_by=media.uploaded_by,
        created_at=media.created_at,
        url=media_service.get_media_url(media)
    )

    return response


@router.delete("/{media_id}")
def delete_media(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    media_id: int
):
    """
    Delete a media item and its files from storage.
    """
    deleted = media_service.delete_media(
        db=db,
        media_id=media_id,
        company_id=current_user.company_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Media not found")

    return {"message": "Media deleted successfully"}


@router.get("/{media_id}/url")
def get_media_download_url(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    media_id: int,
    expires_in: int = Query(3600, ge=60, le=86400, description="URL expiration time in seconds")
):
    """
    Get a pre-signed download URL for a media file.
    """
    media = media_service.get_content_media(
        db=db,
        media_id=media_id,
        company_id=current_user.company_id
    )
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    url = media_service.get_media_url(media, expires_in=expires_in)
    thumbnail_url = media_service.get_thumbnail_url(media, expires_in=expires_in)

    return {
        "url": url,
        "thumbnail_url": thumbnail_url,
        "expires_in": expires_in
    }
