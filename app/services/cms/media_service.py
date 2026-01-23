from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_
from fastapi import UploadFile
from app.models.content_media import ContentMedia
from app.core.object_storage import s3_client, BUCKET_NAME
from app.core.config import settings
import uuid
import os
import io
import mimetypes
from PIL import Image
from datetime import datetime

# Media type mappings
MEDIA_TYPE_MAP = {
    'image/jpeg': 'image',
    'image/png': 'image',
    'image/gif': 'image',
    'image/webp': 'image',
    'image/svg+xml': 'image',
    'audio/mpeg': 'audio',
    'audio/mp3': 'audio',
    'audio/wav': 'audio',
    'audio/ogg': 'audio',
    'audio/webm': 'audio',
    'audio/aac': 'audio',
    'video/mp4': 'video',
    'video/webm': 'video',
    'video/ogg': 'video',
    'video/quicktime': 'video',
    'application/pdf': 'file',
    'application/msword': 'file',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'file',
    'application/vnd.ms-excel': 'file',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'file',
    'text/plain': 'file',
    'text/csv': 'file',
}

# Allowed file extensions by media type
ALLOWED_EXTENSIONS = {
    'image': ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'],
    'audio': ['.mp3', '.wav', '.ogg', '.webm', '.aac', '.m4a'],
    'video': ['.mp4', '.webm', '.ogg', '.mov'],
    'file': ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.csv'],
}

# Max file sizes (in bytes)
MAX_FILE_SIZES = {
    'image': 10 * 1024 * 1024,  # 10 MB
    'audio': 50 * 1024 * 1024,  # 50 MB
    'video': 200 * 1024 * 1024,  # 200 MB
    'file': 25 * 1024 * 1024,  # 25 MB
}

# Thumbnail settings
THUMBNAIL_SIZE = (300, 300)
THUMBNAIL_QUALITY = 85


def get_media_type(mime_type: str, filename: str) -> str:
    """Determine media type from MIME type or filename."""
    if mime_type in MEDIA_TYPE_MAP:
        return MEDIA_TYPE_MAP[mime_type]

    # Fallback to extension
    ext = os.path.splitext(filename)[1].lower()
    for media_type, extensions in ALLOWED_EXTENSIONS.items():
        if ext in extensions:
            return media_type

    return 'file'


def validate_file(file: UploadFile, media_type: Optional[str] = None) -> Tuple[bool, str, str]:
    """
    Validate uploaded file.
    Returns (is_valid, error_message, detected_media_type).
    """
    # Get file extension
    ext = os.path.splitext(file.filename)[1].lower()

    # Detect MIME type
    mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or 'application/octet-stream'

    # Determine media type
    detected_type = get_media_type(mime_type, file.filename)

    # If specific media type requested, validate against it
    if media_type and detected_type != media_type:
        return False, f"File type does not match expected type '{media_type}'", detected_type

    # Check extension is allowed
    all_extensions = []
    for exts in ALLOWED_EXTENSIONS.values():
        all_extensions.extend(exts)

    if ext not in all_extensions:
        return False, f"File extension '{ext}' is not allowed", detected_type

    return True, "", detected_type


def generate_thumbnail(file_content: bytes, filename: str) -> Optional[bytes]:
    """Generate thumbnail for an image."""
    try:
        img = Image.open(io.BytesIO(file_content))

        # Convert to RGB if necessary (for PNG with transparency)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # Create thumbnail
        img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

        # Save to bytes
        thumb_io = io.BytesIO()
        img.save(thumb_io, format='JPEG', quality=THUMBNAIL_QUALITY)
        thumb_io.seek(0)

        return thumb_io.getvalue()
    except Exception as e:
        print(f"Error generating thumbnail: {e}")
        return None


def get_image_dimensions(file_content: bytes) -> Tuple[Optional[int], Optional[int]]:
    """Get image dimensions."""
    try:
        img = Image.open(io.BytesIO(file_content))
        return img.width, img.height
    except Exception as e:
        print(f"Error getting image dimensions: {e}")
        return None, None


def get_audio_duration(file_content: bytes, filename: str) -> Optional[int]:
    """Get audio duration in seconds using mutagen."""
    try:
        from mutagen import File as MutagenFile
        import tempfile

        # Write to temp file for mutagen
        ext = os.path.splitext(filename)[1]
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        try:
            audio = MutagenFile(tmp_path)
            if audio and audio.info:
                return int(audio.info.length)
        finally:
            os.unlink(tmp_path)

        return None
    except ImportError:
        print("mutagen not installed, skipping audio duration extraction")
        return None
    except Exception as e:
        print(f"Error getting audio duration: {e}")
        return None


def get_video_info(file_content: bytes, filename: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """Get video dimensions and duration. Returns (width, height, duration)."""
    try:
        import subprocess
        import tempfile
        import json

        ext = os.path.splitext(filename)[1]
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        try:
            # Use ffprobe to get video info
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', tmp_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                info = json.loads(result.stdout)
                width = None
                height = None
                duration = None

                # Get video stream info
                for stream in info.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        width = stream.get('width')
                        height = stream.get('height')
                        break

                # Get duration
                if 'format' in info:
                    duration_str = info['format'].get('duration')
                    if duration_str:
                        duration = int(float(duration_str))

                return width, height, duration
        finally:
            os.unlink(tmp_path)

        return None, None, None
    except Exception as e:
        print(f"Error getting video info: {e}")
        return None, None, None


def get_content_media(db: Session, media_id: int, company_id: int) -> Optional[ContentMedia]:
    """Get a media item by ID."""
    return db.query(ContentMedia).filter(
        and_(
            ContentMedia.id == media_id,
            ContentMedia.company_id == company_id
        )
    ).first()


def get_content_media_list(
    db: Session,
    company_id: int,
    media_type: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50
) -> List[ContentMedia]:
    """Get media items with filters."""
    query = db.query(ContentMedia).filter(ContentMedia.company_id == company_id)

    if media_type:
        query = query.filter(ContentMedia.media_type == media_type)

    if search:
        query = query.filter(
            ContentMedia.original_filename.ilike(f'%{search}%') |
            ContentMedia.alt_text.ilike(f'%{search}%')
        )

    return query.order_by(ContentMedia.created_at.desc()).offset(skip).limit(limit).all()


def get_content_media_count(
    db: Session,
    company_id: int,
    media_type: Optional[str] = None
) -> int:
    """Get count of media items."""
    query = db.query(ContentMedia).filter(ContentMedia.company_id == company_id)

    if media_type:
        query = query.filter(ContentMedia.media_type == media_type)

    return query.count()


async def upload_media(
    db: Session,
    file: UploadFile,
    company_id: int,
    user_id: int,
    alt_text: Optional[str] = None,
    caption: Optional[str] = None
) -> ContentMedia:
    """Upload a media file to S3 and create database record."""
    # Validate file
    is_valid, error, media_type = validate_file(file)
    if not is_valid:
        raise ValueError(error)

    # Read file content
    file_content = await file.read()
    file_size = len(file_content)

    # Check file size
    max_size = MAX_FILE_SIZES.get(media_type, MAX_FILE_SIZES['file'])
    if file_size > max_size:
        raise ValueError(f"File size exceeds maximum allowed ({max_size // (1024*1024)} MB)")

    # Generate unique filename
    ext = os.path.splitext(file.filename)[1].lower()
    unique_filename = f"{uuid.uuid4()}{ext}"
    s3_key = f"cms/{company_id}/media/{unique_filename}"

    # Get file metadata
    mime_type = file.content_type or mimetypes.guess_type(file.filename)[0]
    width = None
    height = None
    duration = None
    thumbnail_s3_key = None

    # Process based on media type
    if media_type == 'image':
        width, height = get_image_dimensions(file_content)

        # Generate thumbnail
        thumbnail_data = generate_thumbnail(file_content, file.filename)
        if thumbnail_data:
            thumbnail_key = f"cms/{company_id}/thumbnails/{unique_filename.replace(ext, '.jpg')}"
            try:
                s3_client.put_object(
                    Body=thumbnail_data,
                    Bucket=BUCKET_NAME,
                    Key=thumbnail_key,
                    ContentType='image/jpeg'
                )
                thumbnail_s3_key = thumbnail_key
            except Exception as e:
                print(f"Error uploading thumbnail: {e}")

    elif media_type == 'audio':
        duration = get_audio_duration(file_content, file.filename)

    elif media_type == 'video':
        width, height, duration = get_video_info(file_content, file.filename)

    # Upload to S3
    try:
        s3_client.put_object(
            Body=file_content,
            Bucket=BUCKET_NAME,
            Key=s3_key,
            ContentType=mime_type
        )
    except Exception as e:
        raise ValueError(f"Failed to upload file: {str(e)}")

    # Create database record
    db_media = ContentMedia(
        company_id=company_id,
        filename=unique_filename,
        original_filename=file.filename,
        mime_type=mime_type,
        file_size=file_size,
        media_type=media_type,
        s3_bucket=BUCKET_NAME,
        s3_key=s3_key,
        thumbnail_s3_key=thumbnail_s3_key,
        width=width,
        height=height,
        duration=duration,
        alt_text=alt_text,
        caption=caption,
        uploaded_by=user_id
    )

    db.add(db_media)
    db.commit()
    db.refresh(db_media)

    return db_media


def update_media(
    db: Session,
    media_id: int,
    company_id: int,
    alt_text: Optional[str] = None,
    caption: Optional[str] = None
) -> Optional[ContentMedia]:
    """Update media metadata."""
    db_media = get_content_media(db, media_id, company_id)
    if not db_media:
        return None

    if alt_text is not None:
        db_media.alt_text = alt_text
    if caption is not None:
        db_media.caption = caption

    db.commit()
    db.refresh(db_media)

    return db_media


def delete_media(db: Session, media_id: int, company_id: int) -> bool:
    """Delete a media item and its files from S3."""
    db_media = get_content_media(db, media_id, company_id)
    if not db_media:
        return False

    # Delete from S3
    try:
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=db_media.s3_key)
        if db_media.thumbnail_s3_key:
            s3_client.delete_object(Bucket=BUCKET_NAME, Key=db_media.thumbnail_s3_key)
    except Exception as e:
        print(f"Error deleting files from S3: {e}")

    # Delete from database
    db.delete(db_media)
    db.commit()

    return True


def get_media_url(db_media: ContentMedia, expires_in: int = 3600) -> str:
    """Generate a pre-signed URL for accessing the media file."""
    try:
        return s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': BUCKET_NAME, 'Key': db_media.s3_key},
            ExpiresIn=expires_in
        )
    except Exception as e:
        print(f"Error generating presigned URL: {e}")
        return ""


def get_thumbnail_url(db_media: ContentMedia, expires_in: int = 3600) -> Optional[str]:
    """Generate a pre-signed URL for accessing the thumbnail."""
    if not db_media.thumbnail_s3_key:
        return None

    try:
        return s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': BUCKET_NAME, 'Key': db_media.thumbnail_s3_key},
            ExpiresIn=expires_in
        )
    except Exception as e:
        print(f"Error generating thumbnail URL: {e}")
        return None


def increment_usage_count(db: Session, media_id: int, company_id: int) -> None:
    """Increment the usage count for a media item."""
    db_media = get_content_media(db, media_id, company_id)
    if db_media:
        db_media.usage_count += 1
        db.commit()
