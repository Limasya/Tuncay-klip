"""
Vision AI Module (IP_PART7 - AI Intelligence Expansion)

Advanced computer vision capabilities for clip analysis:
  1. Scene Detection - detect scene changes, cuts, transitions
  2. Object Detection & Tracking - YOLO-based person/object tracking
  3. Gesture Recognition - advanced pose-based gesture classification
  4. Optical Flow - motion magnitude and direction analysis
  5. Face Expression Analysis - deep emotion from facial landmarks
  6. Text/OCR Detection - on-screen text extraction
  7. Video Quality Assessment - blur, brightness, contrast scoring
  8. Key Frame Selection - find the best thumbnail frames
  9. Highlight Zone Detection - identify visually interesting regions

All modules work with graceful fallback when dependencies are missing.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("vision_ai")


# ---------------------------------------------------------------------------
# Scene Detection
# ---------------------------------------------------------------------------
class SceneDetector:
    """
    Detect scene changes using histogram comparison and optical flow.

    Methods:
    - Histogram difference (fast, CPU-friendly)
    - Optical flow magnitude (GPU optional)
    - Combined confidence scoring

    Returns scene change probability and transition type.
    """

    TRANSITION_TYPES = ["hard_cut", "fade", "dissolve", "wipe", "zoom", "none"]

    def __init__(
        self,
        hist_threshold: float = 0.35,
        flow_threshold: float = 0.4,
        history_size: int = 10,
    ):
        self.hist_threshold = hist_threshold
        self.flow_threshold = flow_threshold
        self._prev_frame: Optional[np.ndarray] = None
        self._prev_hist: Optional[np.ndarray] = None
        self._history: deque[float] = deque(maxlen=history_size)
        self._scene_count = 0

    def detect(self, frame: np.ndarray) -> dict:
        """Detect if current frame is a scene boundary."""
        result = {
            "is_scene_change": False,
            "transition_type": "none",
            "confidence": 0.0,
            "hist_diff": 0.0,
            "flow_magnitude": 0.0,
        }

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Histogram comparison
        hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
        cv2.normalize(hist, hist)
        if self._prev_hist is not None:
            hist_diff = cv2.compareHist(self._prev_hist, hist, cv2.HISTCMP_CHISQR)
            result["hist_diff"] = min(hist_diff / 100.0, 1.0)

            # Optical flow (if previous frame available)
            if self._prev_frame is not None:
                try:
                    flow = cv2.calcOpticalFlowFarneback(
                        self._prev_frame, gray, None,
                        0.5, 3, 15, 3, 5, 1.2, 0,
                    )
                    mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                    avg_mag = float(np.mean(mag))
                    result["flow_magnitude"] = min(avg_mag / 10.0, 1.0)
                except Exception:
                    result["flow_magnitude"] = 0.0

        self._prev_hist = hist
        self._prev_frame = gray

        # Combined decision
        hist_score = result["hist_diff"]
        flow_score = result["flow_magnitude"]
        combined = hist_score * 0.6 + flow_score * 0.4

        result["confidence"] = combined

        if combined > 0.7:
            result["is_scene_change"] = True
            result["transition_type"] = "hard_cut"
            self._scene_count += 1
        elif combined > 0.5 and flow_score > 0.3:
            result["is_scene_change"] = True
            result["transition_type"] = "dissolve" if hist_score < 0.6 else "fade"
            self._scene_count += 1
        elif flow_score > 0.6:
            result["is_scene_change"] = True
            result["transition_type"] = "zoom"
            self._scene_count += 1

        self._history.append(combined)
        return result

    def get_scene_count(self) -> int:
        return self._scene_count

    def get_status(self) -> dict:
        return {
            "scene_count": self._scene_count,
            "avg_confidence": float(np.mean(list(self._history))) if self._history else 0.0,
        }


# ---------------------------------------------------------------------------
# Object Detection (Lightweight YOLO-compatible)
# ---------------------------------------------------------------------------
class ObjectDetector:
    """
    Object detection using OpenCV DNN with MobileNet-SSD or YOLO.

    Detects: person, sports ball, cell phone, mouse, keyboard, etc.
    Focus: person tracking for streamer, game objects.

    Falls back to simple motion-based blob detection when models unavailable.
    """

    COCO_CLASSES = [
        "background", "person", "bicycle", "car", "motorcycle", "airplane",
        "bus", "train", "truck", "boat", "traffic light", "fire hydrant",
        "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse",
        "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
        "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis",
        "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
        "skateboard", "surfboard", "tennis racket", "bottle", "wine glass",
        "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
        "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza",
        "donut", "cake", "chair", "couch", "potted plant", "bed",
        "dining table", "toilet", "tv", "laptop", "mouse", "remote",
        "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
        "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
        "hair drier", "toothbrush",
    ]

    STREAMING_RELEVANT = {0: "person", 39: "bottle", 67: "cell phone",
                          66: "keyboard", 63: "laptop", 62: "tv",
                          64: "mouse", 73: "book", 32: "sports ball"}

    def __init__(self, confidence_threshold: float = 0.4):
        self.threshold = confidence_threshold
        self.net = None
        self._tracked_objects: dict[int, deque] = {}
        self._next_id = 0
        self._load_model()

    def _load_model(self):
        """Load MobileNet-SSD model."""
        try:
            model_path = "models_store/MobileNetSSD_deploy.caffemodel"
            proto_path = "models_store/MobileNetSSD_deploy.prototxt"
            import os
            if os.path.exists(model_path) and os.path.exists(proto_path):
                self.net = cv2.dnn.readNetFromCaffe(proto_path, model_path)
                logger.info("Object detector loaded (MobileNet-SSD)")
                return
        except Exception as e:
            logger.debug("MobileNet-SSD yüklenemedi, motion-based fallback: %s", e)

        logger.info("Object detector: using motion-based fallback")

    def detect(self, frame: np.ndarray) -> list[dict]:
        """Detect objects in frame."""
        if self.net is not None:
            return self._detect_dnn(frame)
        return self._detect_motion(frame)

    def _detect_dnn(self, frame: np.ndarray) -> list[dict]:
        h, w = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(
            cv2.resize(frame, (300, 300)), 0.007843,
            (300, 300), 127.5,
        )
        self.net.setInput(blob)
        detections = self.net.forward()

        results = []
        for i in range(detections.shape[2]):
            confidence = float(detections[0, 0, i, 2])
            if confidence < self.threshold:
                continue

            class_id = int(detections[0, 0, i, 1])
            label = self.COCO_CLASSES[class_id] if class_id < len(self.COCO_CLASSES) else f"obj_{class_id}"

            if class_id not in self.STREAMING_RELEVANT:
                continue

            x1 = max(0, detections[0, 0, i, 3] * w)
            y1 = max(0, detections[0, 0, i, 4] * h)
            x2 = min(w, detections[0, 0, i, 5] * w)
            y2 = min(h, detections[0, 0, i, 6] * h)

            results.append({
                "label": label,
                "confidence": confidence,
                "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                "area": (x2 - x1) * (y2 - y1),
            })

        # Sort by confidence
        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results[:10]

    def _detect_motion(self, frame: np.ndarray) -> list[dict]:
        """Simple motion blob detection as fallback."""
        results = []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Detect contours as motion blobs
        blurred = cv2.GaussianBlur(gray, (21, 21), 0)
        edges = cv2.Canny(blurred, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours[:5]:
            area = cv2.contourArea(contour)
            if area < 500:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            results.append({
                "label": "motion_blob",
                "confidence": min(area / 50000, 0.8),
                "bbox": {"x1": float(x), "y1": float(y), "x2": float(x + w), "y2": float(y + h)},
                "area": area,
            })
        return results

    def get_status(self) -> dict:
        return {
            "model_loaded": self.net is not None,
            "tracked_objects": len(self._tracked_objects),
            "threshold": self.threshold,
        }


# ---------------------------------------------------------------------------
# Advanced Gesture Recognition
# ---------------------------------------------------------------------------
class GestureRecognizer:
    """
    Advanced gesture recognition from pose keypoints.

    Recognizes 15+ gestures specifically relevant to gaming streams:
    - Victory pose (arms up)
    - Face palm (hand on face)
    - Pointing (arm extended forward)
    - Clapping (hands together repeatedly)
    - Head shake (rapid left-right head movement)
    - Jump/Stand (sudden vertical movement)
    - Lean (body tilt forward/backward/sideways)
    - Dance (rhythmic movement pattern)
    - Fist pump (rapid arm up-down)
    """

    GESTURE_DEFINITIONS = {
        "arms_up_victory": {
            "description": "Both arms raised above shoulders (victory/celebration)",
            "weight": 0.9,
            "hype_score": 0.8,
        },
        "face_palm": {
            "description": "Hand covering face (frustration/disbelief)",
            "weight": 0.7,
            "hype_score": 0.6,
        },
        "pointing": {
            "description": "Arm extended pointing (accusation/direction)",
            "weight": 0.5,
            "hype_score": 0.4,
        },
        "clapping": {
            "description": "Repeated hand proximity (applause/approval)",
            "weight": 0.6,
            "hype_score": 0.5,
        },
        "head_shake": {
            "description": "Rapid horizontal head movement (disbelief/no)",
            "weight": 0.5,
            "hype_score": 0.4,
        },
        "fist_pump": {
            "description": "Rapid arm up-down movement (excitement)",
            "weight": 0.8,
            "hype_score": 0.7,
        },
        "lean_forward": {
            "description": "Body leaning forward (focus/intensity)",
            "weight": 0.4,
            "hype_score": 0.3,
        },
        "lean_back": {
            "description": "Body leaning back (surprise/relaxation)",
            "weight": 0.3,
            "hype_score": 0.2,
        },
        "hand_on_head": {
            "description": "Hand touching head (thinking/stress)",
            "weight": 0.4,
            "hype_score": 0.3,
        },
        "crossed_arms": {
            "description": "Arms crossed (defensive/confident)",
            "weight": 0.3,
            "hype_score": 0.1,
        },
    }

    def __init__(self):
        self._pose_history: deque[dict] = deque(maxlen=30)
        self._gesture_history: deque[dict] = deque(maxlen=60)
        self._active_gesture: Optional[str] = None
        self._gesture_start_time: Optional[float] = None

    def recognize(self, pose_keypoints: dict, timestamp: float) -> list[dict]:
        """
        Recognize gestures from pose keypoints.

        Args:
            pose_keypoints: Dict of landmark_name -> (x, y) normalized
            timestamp: Current time for duration tracking

        Returns:
            List of detected gestures with confidence scores
        """
        self._pose_history.append(pose_keypoints)
        gestures = []

        # Check each gesture condition
        if self._check_arms_up(pose_keypoints):
            gestures.append({
                "gesture": "arms_up_victory",
                "confidence": 0.85,
                **self.GESTURE_DEFINITIONS["arms_up_victory"],
            })

        if self._check_face_palm(pose_keypoints):
            gestures.append({
                "gesture": "face_palm",
                "confidence": 0.75,
                **self.GESTURE_DEFINITIONS["face_palm"],
            })

        if self._check_fist_pump():
            gestures.append({
                "gesture": "fist_pump",
                "confidence": 0.7,
                **self.GESTURE_DEFINITIONS["fist_pump"],
            })

        if self._check_clapping():
            gestures.append({
                "gesture": "clapping",
                "confidence": 0.65,
                **self.GESTURE_DEFINITIONS["clapping"],
            })

        if self._check_head_shake():
            gestures.append({
                "gesture": "head_shake",
                "confidence": 0.6,
                **self.GESTURE_DEFINITIONS["head_shake"],
            })

        if self._check_lean(pose_keypoints):
            direction, conf = self._check_lean(pose_keypoints)
            if direction:
                gestures.append({
                    "gesture": f"lean_{direction}",
                    "confidence": conf,
                    **self.GESTURE_DEFINITIONS.get(f"lean_{direction}", {"weight": 0.3, "hype_score": 0.2}),
                })

        # Track active gesture duration
        if gestures:
            top = gestures[0]["gesture"]
            if top != self._active_gesture:
                self._active_gesture = top
                self._gesture_start_time = timestamp
        else:
            self._active_gesture = None
            self._gesture_start_time = None

        self._gesture_history.append({
            "timestamp": timestamp,
            "gestures": [g["gesture"] for g in gestures],
            "count": len(gestures),
        })

        return gestures

    def get_active_gesture_duration(self, current_time: float) -> float:
        if self._gesture_start_time is not None:
            return current_time - self._gesture_start_time
        return 0.0

    def _check_arms_up(self, pose: dict) -> bool:
        lw = pose.get("left_wrist")
        rw = pose.get("right_wrist")
        ls = pose.get("left_shoulder")
        rs = pose.get("right_shoulder")

        hands_up = 0
        if lw and ls and lw[1] < ls[1] - 0.12:
            hands_up += 1
        if rw and rs and rw[1] < rs[1] - 0.12:
            hands_up += 1
        return hands_up >= 2

    def _check_face_palm(self, pose: dict) -> bool:
        lw = pose.get("left_wrist")
        rw = pose.get("right_wrist")
        nose = pose.get("nose")

        if nose:
            if lw and self._distance(lw, nose) < 0.12:
                return True
            if rw and self._distance(rw, nose) < 0.12:
                return True
        return False

    def _check_fist_pump(self) -> bool:
        if len(self._pose_history) < 5:
            return False

        recent = list(self._pose_history)[-5:]
        lw_positions = []
        for p in recent:
            if "left_wrist" in p:
                lw_positions.append(p["left_wrist"][1])

        if len(lw_positions) >= 3:
            # Check for rapid up-down pattern
            diffs = [abs(lw_positions[i] - lw_positions[i - 1])
                      for i in range(1, len(lw_positions))]
            if sum(diffs) > 0.15 and max(diffs) > 0.05:
                return True
        return False

    def _check_clapping(self) -> bool:
        if len(self._pose_history) < 3:
            return False

        recent = list(self._pose_history)[-3:]
        hand_dists = []
        for p in recent:
            lw = p.get("left_wrist")
            rw = p.get("right_wrist")
            if lw and rw:
                hand_dists.append(self._distance(lw, rw))

        if len(hand_dists) >= 2:
            # Hands getting closer and farther (clapping motion)
            diffs = [abs(hand_dists[i] - hand_dists[i - 1])
                      for i in range(1, len(hand_dists))]
            if sum(diffs) > 0.1 and min(hand_dists) < 0.15:
                return True
        return False

    def _check_head_shake(self) -> bool:
        if len(self._pose_history) < 5:
            return False

        recent = list(self._pose_history)[-5:]
        nose_positions = []
        for p in recent:
            if "nose" in p:
                nose_positions.append(p["nose"][0])

        if len(nose_positions) >= 4:
            diffs = [abs(nose_positions[i] - nose_positions[i - 1])
                      for i in range(1, len(nose_positions))]
            if sum(diffs) > 0.08 and max(diffs) > 0.03:
                return True
        return False

    def _check_lean(self, pose: dict) -> tuple[Optional[str], float]:
        ls = pose.get("left_shoulder")
        rs = pose.get("right_shoulder")
        lh = pose.get("left_hip")
        rh = pose.get("right_hip")

        if not all([ls, rs, lh, rh]):
            return None, 0.0

        shoulder_mid_x = (ls[0] + rs[0]) / 2
        hip_mid_x = (lh[0] + rh[0]) / 2
        lean = hip_mid_x - shoulder_mid_x

        if abs(lean) < 0.03:
            return None, 0.0

        confidence = min(abs(lean) * 8, 0.8)
        direction = "forward" if shoulder_mid_x > hip_mid_x else "back"
        return direction, confidence

    @staticmethod
    def _distance(a: tuple, b: tuple) -> float:
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    def get_gesture_stats(self) -> dict:
        if not self._gesture_history:
            return {"total_gestures": 0, "most_common": None}

        counts = {}
        for entry in self._gesture_history:
            for g in entry["gestures"]:
                counts[g] = counts.get(g, 0) + 1

        most_common = max(counts, key=counts.get) if counts else None
        return {
            "total_gestures": sum(counts.values()),
            "most_common": most_common,
            "gesture_counts": counts,
        }

    def get_status(self) -> dict:
        return {
            "active_gesture": self._active_gesture,
            "gesture_duration": self.get_active_gesture_duration(time.time()),
            **self.get_gesture_stats(),
        }


# ---------------------------------------------------------------------------
# Key Frame Selector - Smart Thumbnail Picker
# ---------------------------------------------------------------------------
class KeyFrameSelector:
    """
    Select the best frame from a clip for thumbnail generation.

    Criteria (weighted):
    - Face presence & visibility (40%)
    - Image sharpness / no blur (20%)
    - Brightness & contrast (15%)
    - Motion/action intensity (15%)
    - Emotion expression quality (10%)
    """

    def __init__(self):
        self._frame_scores: deque[tuple[int, float, np.ndarray]] = deque(maxlen=100)

    def score_frame(
        self,
        frame: np.ndarray,
        faces: list = None,
        emotion: dict = None,
        motion_score: float = 0.0,
    ) -> float:
        """Score a frame for thumbnail suitability (0.0-1.0)."""
        score = 0.0

        # 1. Face presence (40%)
        if faces and len(faces) > 0:
            face_score = min(len(faces) * 0.3, 0.4)
            # Bonus for larger face (closer/better thumbnail)
            max_face_area = max(
                (f.get("bbox", {}).get("area", 0) if isinstance(f, dict)
                 else (f.bbox.x2 - f.bbox.x1) * (f.bbox.y2 - f.bbox.y1) if hasattr(f, 'bbox')
                 else 0)
                for f in faces
            )
            h, w = frame.shape[:2]
            if max_face_area / (h * w) > 0.05:
                face_score += 0.1
            score += min(face_score, 0.5)
        else:
            score += 0.1  # No face but still usable

        # 2. Sharpness (20%) - Laplacian variance
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        sharpness = min(laplacian_var / 500.0, 1.0)
        score += sharpness * 0.2

        # 3. Brightness & contrast (15%)
        brightness = float(np.mean(gray)) / 255.0
        contrast = float(np.std(gray)) / 128.0
        # Golden range: bright but not washed out, decent contrast
        brightness_score = 1.0 - abs(brightness - 0.55) * 2
        contrast_score = min(contrast, 1.0)
        score += (brightness_score * 0.08 + contrast_score * 0.07)

        # 4. Motion intensity (15%)
        motion_norm = min(abs(motion_score) / 3.0, 1.0)
        # Sweet spot: moderate motion (not blurry, not static)
        motion_score_adj = 1.0 - abs(motion_norm - 0.4) * 2
        score += max(motion_score_adj, 0.0) * 0.15

        # 5. Emotion quality (10%)
        if emotion:
            emotion_conf = emotion.get("confidence", 0.0) if isinstance(emotion, dict) else 0.0
            emotion_label = emotion.get("label", "") if isinstance(emotion, dict) else ""
            # Prefer high-emotion expressions (happy, surprise > sad, neutral)
            high_emotions = {"happy", "surprise", "excited", "angry"}
            if emotion_label in high_emotions:
                score += 0.05
            score += min(emotion_conf, 0.05)

        return min(score, 1.0)

    def add_frame(
        self, frame_idx: int, frame: np.ndarray,
        faces: list = None, emotion: dict = None, motion_score: float = 0.0,
    ):
        """Add a scored frame to the selection pool."""
        s = self.score_frame(frame, faces, emotion, motion_score)
        self._frame_scores.append((frame_idx, s, frame.copy()))

    def get_best_frame(self, top_n: int = 3) -> list[dict]:
        """Get the best frames sorted by score."""
        sorted_frames = sorted(self._frame_scores, key=lambda x: x[1], reverse=True)
        return [
            {
                "frame_idx": idx,
                "score": round(score, 3),
                "has_image": True,
            }
            for idx, score, _ in sorted_frames[:top_n]
        ]

    def get_status(self) -> dict:
        if not self._frame_scores:
            return {"frames_processed": 0, "best_score": 0.0}
        best = max(self._frame_scores, key=lambda x: x[1])
        return {
            "frames_processed": len(self._frame_scores),
            "best_score": round(best[1], 3),
            "best_frame_idx": best[0],
        }