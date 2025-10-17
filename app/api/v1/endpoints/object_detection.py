
from fastapi import APIRouter, File, UploadFile, Depends, Response
from app.services.object_detection_service import object_detection_service
from app.schemas.object_detection import ObjectDetectionResponse, ImageSegmentationResponse, PoseEstimationResponse, ObjectTrackingResponse
from app.core.object_storage import s3_client, BUCKET_NAME
import uuid
import os
import requests

router = APIRouter()

@router.get("/image-proxy")
async def image_proxy(url: str):
    response = requests.get(url)
    return Response(content=response.content, media_type=response.headers['Content-Type'])

@router.post("/detect", response_model=ObjectDetectionResponse)
async def detect_objects(file: UploadFile = File(...)):
    image_data = await file.read()
    
    # Save the image to object storage
    file_key = f"object-detection/{uuid.uuid4()}-{file.filename}"
    s3_client.put_object(Bucket=BUCKET_NAME, Key=file_key, Body=image_data)
    
    # Perform object detection
    detections = object_detection_service.detect_objects(image_data)
    
    return {"detections": detections}

@router.post("/segment", response_model=ImageSegmentationResponse)
async def segment_image(file: UploadFile = File(...)):
    image_data = await file.read()
    
    # Save the image to object storage
    file_key = f"object-detection/{uuid.uuid4()}-{file.filename}"
    s3_client.put_object(Bucket=BUCKET_NAME, Key=file_key, Body=image_data)
    
    # Perform image segmentation
    segmentations = object_detection_service.segment_image(image_data)
    
    return {"segmentations": segmentations}

@router.post("/pose", response_model=PoseEstimationResponse)
async def estimate_pose(file: UploadFile = File(...)):
    image_data = await file.read()
    
    # Save the image to object storage
    file_key = f"object-detection/{uuid.uuid4()}-{file.filename}"
    s3_client.put_object(Bucket=BUCKET_NAME, Key=file_key, Body=image_data)
    
    # Perform pose estimation
    poses = object_detection_service.estimate_pose(image_data)
    
    return {"poses": poses}

@router.post("/track", response_model=ObjectTrackingResponse)
async def track_objects(file: UploadFile = File(...)):
    # Save the video file temporarily
    temp_video_path = f"/tmp/{uuid.uuid4()}-{file.filename}"
    with open(temp_video_path, "wb") as buffer:
        buffer.write(await file.read())
    
    # Perform object tracking
    tracks = object_detection_service.track_objects(temp_video_path)
    
    # Clean up the temporary file
    os.remove(temp_video_path)
    
    return {"tracks": tracks}
