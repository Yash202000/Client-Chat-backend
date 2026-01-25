from sqlalchemy.orm import Session
from app.models import ai_image as models_ai_image
from app.schemas import ai_image as schemas_ai_image

def get_ai_image(db: Session, image_id: int):
    return db.query(models_ai_image.AIImage).filter(models_ai_image.AIImage.id == image_id).first()

def get_ai_images(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models_ai_image.AIImage).offset(skip).limit(limit).all()

def create_ai_image(db: Session, prompt: str, image_url: str, generation_params: dict = None):
    """Create an AI image record in the database."""
    db_image = models_ai_image.AIImage(
        prompt=prompt,
        generation_params=generation_params or {},
        image_url=image_url
    )
    db.add(db_image)
    db.commit()
    db.refresh(db_image)
    return db_image

def delete_ai_image(db: Session, image_id: int):
    db_image = get_ai_image(db, image_id)
    if db_image:
        db.delete(db_image)
        db.commit()
    return db_image
