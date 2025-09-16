
from ultralytics import YOLO
import cv2
import numpy as np

class ObjectDetectionService:
    def __init__(self, detection_model_path='yolov8n.pt', segmentation_model_path='yolov8n-seg.pt', pose_model_path='yolov8n-pose.pt'):
        self.detection_model = YOLO(detection_model_path)
        self.segmentation_model = YOLO(segmentation_model_path)
        self.pose_model = YOLO(pose_model_path)

    def detect_objects(self, image_data: bytes):
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        results = self.detection_model(img)
        
        detections = []
        for result in results:
            for box in result.boxes:
                detections.append({
                    "label": self.detection_model.names[int(box.cls)],
                    "confidence": float(box.conf),
                    "box": [int(x) for x in box.xyxy[0]],
                })
        
        return detections

    def segment_image(self, image_data: bytes):
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        results = self.segmentation_model(img)
        
        segmentations = []
        for result in results:
            if result.masks is not None:
                for i, mask in enumerate(result.masks.data):
                    segmentations.append({
                        "label": self.segmentation_model.names[int(result.boxes[i].cls)],
                        "confidence": float(result.boxes[i].conf),
                        "box": [int(x) for x in result.boxes[i].xyxy[0]],
                        "mask": mask.cpu().numpy().tolist(),
                    })
        
        return segmentations

    def estimate_pose(self, image_data: bytes):
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        results = self.pose_model(img)
        
        poses = []
        for result in results:
            if result.keypoints is not None:
                for keypoint in result.keypoints.data:
                    poses.append(keypoint.cpu().numpy().tolist())
        
        return poses

    def track_objects(self, video_path: str):
        results = self.detection_model.track(source=video_path, show=False, tracker="bytetrack.yaml")
        tracks = []
        for result in results:
            if result.boxes is not None:
                for box in result.boxes:
                    tracks.append({
                        "label": self.detection_model.names[int(box.cls)],
                        "confidence": float(box.conf),
                        "box": [int(x) for x in box.xyxy[0]],
                        "track_id": int(box.id) if box.id is not None else -1,
                    })
        return tracks

object_detection_service = ObjectDetectionService()
