import uuid
from sqlalchemy.orm import Session
from app.core.object_storage import s3_client, BUCKET_NAME, endpoint_url
from app.crud import crud_ai_image
from app.schemas import ai_image as schemas_ai_image
from app.llm_providers import gemini_provider
import os

def create_and_upload_ai_image(db: Session, image_data: schemas_ai_image.AIImageCreate):
    # 1. Generate the image
    image_data = gemini_provider.generate_image(prompt=image_data.prompt)
    
    # 2. Upload to MinIO
    filename = f"{uuid.uuid4()}.png"
    
    s3_client.put_object(Bucket=BUCKET_NAME, Key=filename, Body=image_data, ContentType='image/png')
    
    # 3. Construct the public URL
    image_url = f"{endpoint_url}/{BUCKET_NAME}/{filename}"
    # 4. Save to database
    return crud_ai_image.create_ai_image(db=db, image=image_data, image_url=image_url)

def delete_ai_image(db: Session, image_id: int):
    # In a real implementation, you would also delete the image from MinIO
    return crud_ai_image.delete_ai_image(db=db, image_id=image_id)
