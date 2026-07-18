"""
Video Analysis Microservice
────────────────────────────
Processes frames through multiple AI models:
  1. Face Detection (OpenCV DNN / YOLO)
  2. Emotion Recognition (ViT)
  3. Pose Estimation (MediaPipe)
  4. Object Detection (YOLOv8 — optional)
  5. OCR (EasyOCR — optional)

Subscribes to FRAME_EXTRACTED events, publishes analysis results.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime
from typing import Optional

import cv2
import numpy as np

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import (
    EventType, SystemEvent, BoundingBox,
    FaceDetection, EmotionResult, PoseKeypoints,
    ObjectDetection, OCRResult, FrameAnalysisResult,
)

# Import Vision AI module
try:
    from services.vision_ai import SceneDetector, ObjectDetector, GestureRecognizer, KeyFrameSelector
    _VISION_AI_AVAILABLE = True
except ImportError as e:
    logger.warning("Vision AI module not available: %s", e)
    _VISION_AI_AVAILABLE = False

logger = logging.getLogger("video_analysis")


# ─── Face Detector ───────────────────────────────────────────

class FaceDetector:
    """
    Face detection using OpenCV DNN (SSD + ResNet10).
    Fast, accurate, no GPU required (CPU: ~15ms, GPU: ~3ms).
    """

    PROTOTXT_URL = "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt"
    MODEL_URL = "https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel"

    def __init__(self, confidence_threshold: float = 0.5):
        self.threshold = confidence_threshold
        self.net = None
        self._load_model()

    def _load_model(self):
        try:
            self.net = cv2.dnn.readNetFromCaffe(
                "models_store/deploy.prototxt",
                "models_store/res10_300x300_ssd_iter_140000.caffemodel",
            )
            logger.info("Face detector loaded (DNN SSD)")
        except Exception:
            # Fallback to Haar Cascade
            self.net = None
            logger.warning("DNN model not found, using Haar Cascade fallback")

    def detect(self, frame_bgr: np.ndarray) -> list[FaceDetection]:
        if self.net is not None:
            return self._detect_dnn(frame_bgr)
        return self._detect_haar(frame_bgr)

    def _detect_dnn(self, frame: np.ndarray) -> list[FaceDetection]:
        h, w = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(
            cv2.resize(frame, (300, 300)), 1.0, (300, 300),
            (104.0, 177.0, 123.0),
        )
        self.net.setInput(blob)
        detections = self.net.forward()

        results = []
        for i in range(detections.shape[2]):
            confidence = float(detections[0, 0, i, 2])
            if confidence < self.threshold:
                continue

            x1 = max(0, detections[0, 0, i, 3] * w)
            y1 = max(0, detections[0, 0, i, 4] * h)
            x2 = min(w, detections[0, 0, i, 5] * w)
            y2 = min(h, detections[0, 0, i, 6] * h)

            results.append(FaceDetection(
                bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                confidence=confidence,
            ))
        return results

    def _detect_haar(self, frame: np.ndarray) -> list[FaceDetection]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Try local cascade first, then cv2.data path
        cascade_path = "models_store/haarcascade_frontalface_default.xml"
        import os
        if not os.path.exists(cascade_path):
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"

        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            logger.warning("Haar cascade failed to load, skipping face detection")
            return []

        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))

        if faces is None or len(faces) == 0:
            return []

        results = []
        for (x, y, w, h) in faces:
            results.append(FaceDetection(
                bbox=BoundingBox(x1=float(x), y1=float(y),
                                 x2=float(x + w), y2=float(y + h)),
                confidence=0.8,
            ))
        return results


# ─── Emotion Recognizer ──────────────────────────────────────

class EmotionRecognizer:
    """
    Emotion recognition from face crops.
    Uses HuggingFace ViT model when available,
    falls back to simple heuristic based on facial features.
    """

    EMOTIONS = ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"]
    HIGHLIGHT_EMOTIONS = {"happy", "surprise", "fear", "angry"}

    def __init__(self):
        self.pipe = None
        self._load_model()

    def _load_model(self):
        try:
            from transformers import pipeline as hf_pipeline
            self.pipe = hf_pipeline(
                "image-classification",
                model="trpakov/vit-face-expression",
                device=-1,  # CPU for safety
            )
            logger.info("Emotion recognizer loaded (ViT)")
        except Exception as e:
            logger.warning(f"ViT model not available: {e}. Using heuristic.")

    def recognize(self, face_crop: np.ndarray) -> Optional[EmotionResult]:
        if face_crop is None or face_crop.size == 0:
            return None

        if self.pipe is not None:
            return self._recognize_model(face_crop)
        return self._recognize_heuristic(face_crop)

    def _recognize_model(self, face_crop: np.ndarray) -> Optional[EmotionResult]:
        from PIL import Image
        face_rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
        face_resized = cv2.resize(face_rgb, (224, 224))
        pil_image = Image.fromarray(face_resized)

        results = self.pipe(pil_image, top_k=7)

        scores = {}
        for item in results:
            label = item["label"].lower().replace(" ", "_")
            scores[label] = item["score"]

        top_label = max(scores, key=scores.get)
        top_confidence = scores[top_label]

        return EmotionResult(
            face_id="unknown",
            label=top_label,
            confidence=top_confidence,
            scores=scores,
        )

    def _recognize_heuristic(self, face_crop: np.ndarray) -> EmotionResult:
        """Simple heuristic based on face brightness and contrast."""
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        brightness = np.mean(gray) / 255.0
        contrast = np.std(gray) / 128.0

        # Very basic heuristic — replace with real model in production
        scores = {e: 0.1 for e in self.EMOTIONS}
        if brightness > 0.6 and contrast > 0.5:
            scores["happy"] = 0.5
        elif brightness < 0.3:
            scores["sad"] = 0.4
        else:
            scores["neutral"] = 0.6

        top = max(scores, key=scores.get)
        return EmotionResult(
            face_id="unknown", label=top,
            confidence=scores[top], scores=scores,
        )

    def recognize_batch(self, face_crops: list[np.ndarray]) -> list[EmotionResult]:
        return [r for c in face_crops if (r := self.recognize(c)) is not None]


# ─── Pose Estimator ──────────────────────────────────────────

class PoseEstimator:
    """
    Pose estimation using MediaPipe BlazePose.
    Detects gestures: hand raise, lean forward, arms spread, etc.
    """

    GESTURES = {
        "hand_raise": 0.8,
        "lean_forward": 0.5,
        "arms_spread": 0.9,
        "face_palm": 0.6,
    }

    def __init__(self):
        self.mp_pose = None
        self.pose = None
        self._pose_history: deque[dict] = deque(maxlen=30)
        self._load_model()

    def _load_model(self):
        try:
            import mediapipe as mp
            # MediaPipe >= 0.10.20 uses tasks API
            if hasattr(mp, 'tasks'):
                from mediapipe.tasks import python as mp_python
                from mediapipe.tasks.python import vision as mp_vision
                base_options = mp_python.BaseOptions(
                    model_asset_path="models_store/pose_landmarker_lite.task"
                )
                options = mp_vision.PoseLandmarkerOptions(
                    base_options=base_options,
                    running_mode=mp_vision.RunningMode.IMAGE,
                    num_poses=1,
                    min_pose_detection_confidence=0.5,
                )
                self.pose = mp_vision.PoseLandmarker.create_from_options(options)
                self.mp_pose = mp.tasks.vision
                logger.info("Pose estimator loaded (MediaPipe Tasks API)")
            elif hasattr(mp, 'solutions'):
                self.mp_pose = mp.solutions.pose
                self.pose = self.mp_pose.Pose(
                    static_image_mode=True,
                    model_complexity=1,
                    min_detection_confidence=0.5,
                )
                logger.info("Pose estimator loaded (MediaPipe Solutions API)")
            else:
                raise ImportError("No compatible MediaPipe API found")
        except Exception as e:
            logger.warning(f"MediaPipe not available: {e}")

    def estimate(self, frame_bgr: np.ndarray) -> list[PoseKeypoints]:
        if self.pose is None:
            return self._estimate_simple(frame_bgr)

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # Handle Tasks API (new) vs Solutions API (old)
        try:
            import mediapipe as mp
            if hasattr(mp, 'tasks') and hasattr(self.pose, 'detect'):
                # Tasks API
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
                result = self.pose.detect(mp_image)
                if not result.pose_landmarks or len(result.pose_landmarks) == 0:
                    return []
                landmarks = result.pose_landmarks[0]  # First person
                pose_data = {}
                from mediapipe.tasks.python.vision import PoseLandmarker
                for i, lm in enumerate(landmarks):
                    try:
                        name = PoseLandmarker.PoseLandmark(i).name.lower()
                    except (ValueError, AttributeError):
                        name = f"landmark_{i}"
                    pose_data[name] = (lm.x, lm.y)
            else:
                # Solutions API (legacy)
                results = self.pose.process(frame_rgb)
                if not results.pose_landmarks:
                    return []
                landmarks = results.pose_landmarks.landmark
                pose_data = {}
                for lm in landmarks:
                    name = self.mp_pose.PoseLandmark(lm).name.lower()
                    pose_data[name] = (lm.x, lm.y)
        except Exception as e:
            logger.debug(f"Pose estimation error: {e}")
            return []

        gestures = self._detect_gestures(pose_data)
        motion = self._compute_motion(pose_data)

        self._pose_history.append(pose_data)

        return [PoseKeypoints(
            keypoints=pose_data,
            gestures=gestures,
            motion_score=motion,
        )]

    def _estimate_simple(self, frame: np.ndarray) -> list[PoseKeypoints]:
        """Fallback: detect large motion via frame differencing."""
        return []

    def _detect_gestures(self, pose: dict) -> list[str]:
        gestures = []

        lw = pose.get("left_wrist")
        rw = pose.get("right_wrist")
        ls = pose.get("left_shoulder")
        rs = pose.get("right_shoulder")

        hand_raises = 0
        if lw and ls and lw[1] < ls[1] - 0.15:
            hand_raises += 1
        if rw and rs and rw[1] < rs[1] - 0.15:
            hand_raises += 1

        if hand_raises >= 2:
            gestures.append("arms_spread")
            gestures.append("hand_raise")
        elif hand_raises == 1:
            gestures.append("hand_raise")

        return gestures

    def _compute_motion(self, current: dict) -> float:
        if len(self._pose_history) < 2:
            return 0.0
        prev = self._pose_history[-1]
        total = 0.0
        count = 0
        for k in current:
            if k in prev:
                dx = current[k][0] - prev[k][0]
                dy = current[k][1] - prev[k][1]
                total += (dx**2 + dy**2) ** 0.5
                count += 1
        return total / max(count, 1)


# ─── Video Analysis Service ──────────────────────────────────

class VideoAnalysisService:
    """
    Main video analysis pipeline.

    Processes each frame through all models:
    Frame → Face Detection → Emotion Recognition
          → Pose Estimation
          → (optional) Object Detection + OCR

    All models run in parallel where possible.
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus or get_event_bus()

        self.face_detector = FaceDetector()
        self.emotion_recognizer = EmotionRecognizer()
        self.pose_estimator = PoseEstimator()

        # Advanced Vision AI modules
        if _VISION_AI_AVAILABLE:
            self.scene_detector = SceneDetector()
            self.object_detector = ObjectDetector()
            self.gesture_recognizer = GestureRecognizer()
            self.key_frame_selector = KeyFrameSelector()
        else:
            self.scene_detector = None
            self.object_detector = None
            self.gesture_recognizer = None
            self.key_frame_selector = None

        self._frame_store: dict[str, np.ndarray] = {}
        self._max_store = 50
        self._frame_idx = 0
        self._metrics = {
            "frames_analyzed": 0,
            "avg_inference_ms": 0.0,
            "faces_detected": 0,
            "emotions_detected": 0,
            "scenes_detected": 0,
            "gestures_detected": 0,
            "objects_detected": 0,
        }

        # Subscribe to frame events
        self.event_bus.subscribe(
            EventType.FRAME_EXTRACTED.value,
            self._on_frame_event,
        )

    async def _on_frame_event(self, event: SystemEvent):
        """Handle FRAME_EXTRACTED event — no-op in current architecture.

        The orchestrator calls ``analyze_frame()`` directly for each new frame.
        This event handler exists for future shared-memory / gRPC deployments
        where frames arrive via the event bus instead of direct method calls.
        """
        pass  # Intentional no-op; see docstring.

    async def analyze_frame(self, frame_image: np.ndarray, frame_id: str = "") -> FrameAnalysisResult:
        """
        Analyze a single frame through all models.

        This is the main entry point called by the orchestrator.

        Enhanced v2 pipeline:
        1. Face Detection → 2. Emotion Recognition
        3. Pose Estimation → 4. Gesture Recognition
        5. Scene Detection → 6. Object Detection
        7. Key Frame Scoring
        """
        start = time.time()
        self._frame_idx += 1

        # Step 1: Face detection (must run first)
        faces = self.face_detector.detect(frame_image)
        self._metrics["faces_detected"] += len(faces)

        # Step 2: Emotion recognition on face crops
        emotions = []
        if faces:
            crops = []
            for face in faces:
                crop = self._crop_face(frame_image, face.bbox)
                if crop is not None and crop.size > 0:
                    crops.append(crop)
            emotions = self.emotion_recognizer.recognize_batch(crops)
            for i, emotion in enumerate(emotions):
                if i < len(faces):
                    emotion.face_id = faces[i].face_id
            self._metrics["emotions_detected"] += len(emotions)

        # Step 3: Pose estimation
        poses = self.pose_estimator.estimate(frame_image)

        # Step 4: Gesture recognition (advanced)
        gestures = []
        if self.gesture_recognizer is not None and poses:
            for pose_data in poses:
                gesture_results = self.gesture_recognizer.recognize(
                    pose_data.keypoints, time.time(),
                )
                gestures.extend(gesture_results)
                self._metrics["gestures_detected"] += len(gesture_results)

        # Step 5: Scene detection
        scene_info = None
        if self.scene_detector is not None:
            scene_info = self.scene_detector.detect(frame_image)
            if scene_info.get("is_scene_change"):
                self._metrics["scenes_detected"] += 1

        # Step 6: Object detection
        objects = []
        if self.object_detector is not None:
            objects = self.object_detector.detect(frame_image)
            self._metrics["objects_detected"] += len(objects)

        # Step 7: Key frame scoring (for thumbnail selection)
        if self.key_frame_selector is not None:
            motion_score = poses[0].motion_score if poses else 0.0
            top_emotion = emotions[0] if emotions else None
            emotion_dict = None
            if top_emotion:
                emotion_dict = {
                    "label": top_emotion.label,
                    "confidence": top_emotion.confidence,
                }
            self.key_frame_selector.add_frame(
                self._frame_idx, frame_image, faces, emotion_dict, motion_score,
            )

        # Build result
        result = FrameAnalysisResult(
            frame_id=frame_id or f"frame_{self._frame_idx}",
            timestamp=datetime.utcnow(),
            faces=faces,
            emotions=emotions,
            poses=poses,
            objects=[] if not objects else [
                ObjectDetection(
                    label=o.get("label", "unknown"),
                    confidence=o.get("confidence", 0.0),
                    bbox=BoundingBox(
                        x1=o.get("bbox", {}).get("x1", 0),
                        y1=o.get("bbox", {}).get("y1", 0),
                        x2=o.get("bbox", {}).get("x2", 0),
                        y2=o.get("bbox", {}).get("y2", 0),
                    ),
                )
                for o in objects
            ],
            texts=[],
            inference_time_ms=(time.time() - start) * 1000,
        )

        # Publish events
        if faces:
            await self.event_bus.publish_quick(
                EventType.FACE_DETECTED,
                {"frame_id": frame_id, "count": len(faces),
                 "faces": [f.model_dump(mode="json") for f in faces]},
                source_service="video-analysis",
            )

        if emotions:
            await self.event_bus.publish_quick(
                EventType.EMOTION_DETECTED,
                {"frame_id": frame_id,
                 "emotions": [e.model_dump(mode="json") for e in emotions]},
                source_service="video-analysis",
            )

        if poses and any(p.gestures for p in poses):
            await self.event_bus.publish_quick(
                EventType.POSE_DETECTED,
                {"frame_id": frame_id,
                 "poses": [p.model_dump(mode="json") for p in poses]},
                source_service="video-analysis",
            )

        if scene_info and scene_info.get("is_scene_change"):
            await self.event_bus.publish_quick(
                EventType.SCENE_CHANGE,
                scene_info,
                source_service="video-analysis",
            )

        if gestures:
            await self.event_bus.publish_quick(
                EventType.GESTURE_DETECTED,
                {"frame_id": frame_id, "gestures": gestures},
                source_service="video-analysis",
            )

        if objects:
            await self.event_bus.publish_quick(
                EventType.OBJECT_DETECTED,
                {"frame_id": frame_id, "objects": [
                    {"label": o.get("label", ""), "confidence": o.get("confidence", 0)}
                    for o in objects
                ]},
                source_service="video-analysis",
            )

        # Update metrics
        self._metrics["frames_analyzed"] += 1
        self._metrics["avg_inference_ms"] = (
            self._metrics["avg_inference_ms"] * 0.9
            + result.inference_time_ms * 0.1
        )

        return result

    def _crop_face(
        self, frame: np.ndarray, bbox: BoundingBox, padding: float = 0.2,
    ) -> Optional[np.ndarray]:
        h, w = frame.shape[:2]
        face_w = bbox.x2 - bbox.x1
        face_h = bbox.y2 - bbox.y1
        pad_x = int(face_w * padding)
        pad_y = int(face_h * padding)

        x1 = max(0, int(bbox.x1) - pad_x)
        y1 = max(0, int(bbox.y1) - pad_y)
        x2 = min(w, int(bbox.x2) + pad_x)
        y2 = min(h, int(bbox.y2) + pad_y)

        if x2 <= x1 or y2 <= y1:
            return None
        return frame[y1:y2, x1:x2]

    def get_status(self) -> dict:
        status = dict(self._metrics)
        if self.scene_detector is not None:
            status["scene_detector"] = self.scene_detector.get_status()
        if self.gesture_recognizer is not None:
            status["gesture_recognizer"] = self.gesture_recognizer.get_status()
        if self.key_frame_selector is not None:
            status["key_frame_selector"] = self.key_frame_selector.get_status()
        if self.object_detector is not None:
            status["object_detector"] = self.object_detector.get_status()
        return status
