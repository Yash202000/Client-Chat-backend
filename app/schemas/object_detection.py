
from pydantic import BaseModel
from typing import List, Tuple

class Detection(BaseModel):
    label: str
    confidence: float
    box: List[int]

class ObjectDetectionResponse(BaseModel):
    detections: List[Detection]

class Segmentation(BaseModel):
    label: str
    confidence: float
    box: List[int]
    mask: List[List[float]]

class ImageSegmentationResponse(BaseModel):
    segmentations: List[Segmentation]

class Pose(BaseModel):
    keypoints: List[List[float]]

class PoseEstimationResponse(BaseModel):
    poses: List[Pose]

class Track(BaseModel):
    label: str
    confidence: float
    box: List[int]
    track_id: int

class ObjectTrackingResponse(BaseModel):
    tracks: List[Track]
