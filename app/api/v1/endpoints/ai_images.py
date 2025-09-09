
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user
from app.services import ai_image_service
from app.schemas import ai_image as schemas_ai_image

router = APIRouter()

@router.post("/", response_model=schemas_ai_image.AIImage)
def create_ai_image(
    image_data: schemas_ai_image.AIImageCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return ai_image_service.create_and_upload_ai_image(db=db, image_data=image_data)

@router.get("/", response_model=List[schemas_ai_image.AIImage])
def read_ai_images(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    images = ai_image_service.crud_ai_image.get_ai_images(db, skip=skip, limit=limit)
    return images

@router.delete("/{image_id}", response_model=schemas_ai_image.AIImage)
def delete_ai_image(
    image_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_image = ai_image_service.delete_ai_image(db=db, image_id=image_id)
    if db_image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return db_image
