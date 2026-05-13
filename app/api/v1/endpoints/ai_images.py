from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
import io

from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.core.object_storage import s3_client, BUCKET_NAME
from app.models import user as models_user
from app.services import ai_image_service
from app.schemas import ai_image as schemas_ai_image

router = APIRouter()


@router.get("/file/{filename:path}")
def serve_image_file(filename: str):
    """
    Proxy endpoint to serve images from MinIO storage.
    This keeps MinIO private and serves images through the backend.
    """
    try:
        # Construct the full key
        key = f"ai-images/{filename}" if not filename.startswith("ai-images/") else filename

        # Get the object from MinIO
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=key)

        # Get content type
        content_type = response.get('ContentType', 'image/png')

        # Stream the image
        return StreamingResponse(
            response['Body'],
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=86400",  # Cache for 1 day
                "Content-Disposition": f"inline; filename={filename.split('/')[-1]}"
            }
        )
    except s3_client.exceptions.NoSuchKey:
        raise HTTPException(status_code=404, detail="Image not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to serve image")

@router.post("/", response_model=schemas_ai_image.AIImage, dependencies=[Depends(require_permission("image:create"))])
def create_ai_image(
    image_data: schemas_ai_image.AIImageCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return ai_image_service.create_and_upload_ai_image(
        db=db,
        image_data=image_data,
        company_id=current_user.company_id
    )

@router.get("/", response_model=List[schemas_ai_image.AIImage], dependencies=[Depends(require_permission("image:read"))])
def read_ai_images(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    # Uses service to get images with fresh pre-signed URLs
    images = ai_image_service.get_ai_images(db, skip=skip, limit=limit)
    return images

@router.delete("/{image_id}", response_model=schemas_ai_image.AIImage, dependencies=[Depends(require_permission("image:delete"))])
def delete_ai_image(
    image_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_image = ai_image_service.delete_ai_image(db=db, image_id=image_id)
    if db_image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return db_image
