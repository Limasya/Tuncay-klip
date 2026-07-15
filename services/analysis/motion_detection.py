"""
Hareket ve olay tespit servisi.
- Optical Flow (Farneback) ile hareket büyüklüğü
- MediaPipe Pose ile vücut pozisyonları ve hareketleri
- Ani hareket / önemli olay tespiti
"""
import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class OpticalFlowAnalyzer:
    """
    Farneback Dense Optical Flow ile kareler arası hareket analizi.
    """

    def __init__(self):
        self._prev_gray: Optional[np.ndarray] = None

    def compute_flow(self, frame: np.ndarray) -> Dict:
        """
        Mevcut frame ile önceki frame arasındaki optik akışı hesaplar.

        Returns:
            {
                "magnitude": float,       # ortalama hareket büyüklüğü
                "max_magnitude": float,    # maksimum hareket
                "flow_direction": str,     # baskın yön
                "significant_motion": bool
            }
        """
        import cv2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if self._prev_gray is None:
            self._prev_gray = gray
            return {
                "magnitude": 0.0,
                "max_magnitude": 0.0,
                "flow_direction": "none",
                "significant_motion": False,
            }

        # Farneback Dense Optical Flow
        flow = cv2.calcOpticalFlowFarneback(
            self._prev_gray, gray,
            None,
            pyr_scale=0.5,
            levels=3,
            winsize=15,
            iterations=3,
            poly_n=5,
            poly_sigma=1.2,
            flags=0,
        )

        self._prev_gray = gray

        # Hareket büyüklükleri
        magnitude = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        avg_magnitude = float(np.mean(magnitude))
        max_magnitude = float(np.percentile(magnitude, 99))

        # Baskın yön
        angle = np.arctan2(flow[..., 1], flow[..., 0])
        avg_angle = float(np.mean(angle))
        direction = self._angle_to_direction(avg_angle)

        # Önemli hareket eşiği
        threshold = settings.motion_sensitivity * 5.0  # Ayarlanabilir
        significant = avg_magnitude > threshold or max_magnitude > threshold * 3

        return {
            "magnitude": avg_magnitude,
            "max_magnitude": max_magnitude,
            "flow_direction": direction,
            "significant_motion": significant,
        }

    def _angle_to_direction(self, angle_rad: float) -> str:
        """Radyan açıyı yön etiketine çevirir."""
        import math
        deg = math.degrees(angle_rad) % 360
        if deg < 45 or deg >= 315:
            return "right"
        elif deg < 135:
            return "down"
        elif deg < 225:
            return "left"
        else:
            return "up"

    def reset(self):
        self._prev_gray = None


class PoseAnalyzer:
    """
    MediaPipe Pose ile vücut pozisyonu ve hareket analizi.
    Ani jestler, el kaldırma, ayağa kalkma gibi olayları tespit eder.
    """

    def __init__(self):
        self._mp_pose = None
        self._pose = None
        self._prev_landmarks = None

    def _load_model(self):
        """MediaPipe Pose modelini yükle."""
        try:
            import mediapipe as mp
            self._mp_pose = mp.solutions.pose
            self._pose = self._mp_pose.Pose(
                static_image_mode=False,
                model_complexity=1,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            logger.info("MediaPipe Pose modeli yüklendi.")
        except ImportError:
            logger.warning("MediaPipe yüklü değil, pose analizi devre dışı.")

    def analyze(self, frame: np.ndarray) -> Dict:
        """
        Frame'deki vücut pozunu analiz eder.

        Returns:
            {
                "pose_detected": bool,
                "landmarks": dict,
                "gesture": str,           # "hand_raise", "stand_up", vb.
                "gesture_confidence": float,
                "significant_movement": bool,
                "movement_score": float
            }
        """
        if self._pose is None:
            self._load_model()

        if self._pose is None:
            return self._empty_result()

        import cv2
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._pose.process(rgb)

        if not results.pose_landmarks:
            self._prev_landmarks = None
            return self._empty_result()

        landmarks = {}
        for idx, lm in enumerate(results.pose_landmarks.landmark):
            landmarks[idx] = {
                "x": lm.x, "y": lm.y, "z": lm.z,
                "visibility": lm.visibility,
            }

        # Jest tespiti
        gesture, confidence = self._detect_gesture(landmarks)

        # Hareket skoru (önceki landmark'lara göre fark)
        movement_score = self._compute_movement(landmarks)
        self._prev_landmarks = landmarks

        return {
            "pose_detected": True,
            "landmarks": landmarks,
            "gesture": gesture,
            "gesture_confidence": confidence,
            "significant_movement": movement_score > settings.motion_sensitivity,
            "movement_score": movement_score,
        }

    def _detect_gesture(self, landmarks: Dict) -> Tuple[str, float]:
        """Landmark'lardan jest/pose tespiti."""
        # El kaldırma: bilek (wrist) omuzdan yukarıda mı?
        left_wrist = landmarks.get(15, {})
        right_wrist = landmarks.get(16, {})
        left_shoulder = landmarks.get(11, {})
        right_shoulder = landmarks.get(12, {})

        if left_wrist and left_shoulder:
            if left_wrist.get("y", 1) < left_shoulder.get("y", 0) - 0.1:
                return "hand_raise_left", left_wrist.get("visibility", 0.5)

        if right_wrist and right_shoulder:
            if right_wrist.get("y", 1) < right_shoulder.get("y", 0) - 0.1:
                return "hand_raise_right", right_wrist.get("visibility", 0.5)

        # Her iki el havada
        if (left_wrist and right_wrist and left_shoulder and right_shoulder):
            if (left_wrist.get("y", 1) < left_shoulder.get("y", 0) - 0.1 and
                    right_wrist.get("y", 1) < right_shoulder.get("y", 0) - 0.1):
                return "hands_up", 0.9

        return "none", 0.0

    def _compute_movement(self, landmarks: Dict) -> float:
        """Önceki ve şimdiki landmark'lar arası hareket skoru."""
        if not self._prev_landmarks:
            return 0.0

        total_diff = 0.0
        count = 0
        for idx in landmarks:
            if idx in self._prev_landmarks:
                dx = landmarks[idx]["x"] - self._prev_landmarks[idx]["x"]
                dy = landmarks[idx]["y"] - self._prev_landmarks[idx]["y"]
                total_diff += np.sqrt(dx ** 2 + dy ** 2)
                count += 1

        return float(total_diff / max(count, 1))

    def _empty_result(self) -> Dict:
        return {
            "pose_detected": False,
            "landmarks": {},
            "gesture": "none",
            "gesture_confidence": 0.0,
            "significant_movement": False,
            "movement_score": 0.0,
        }


class MotionAnalyzer:
    """
    Birleşik hareket analiz servisi.
    Optical Flow + Pose analizini birleştirerek olay skoru üretir.
    """

    def __init__(self):
        self.optical_flow = OpticalFlowAnalyzer()
        self.pose_analyzer = PoseAnalyzer()

    def analyze_frame(self, frame: np.ndarray) -> Dict:
        """
        Frame üzerinde tam hareket analizi yapar.

        Returns:
            {
                "optical_flow": {...},
                "pose": {...},
                "motion_score": float,
                "is_significant_event": bool,
                "event_type": str
            }
        """
        flow_result = self.optical_flow.compute_flow(frame)
        pose_result = self.pose_analyzer.analyze(frame)

        # Birleşik hareket skoru
        flow_score = min(flow_result["magnitude"] / 10.0, 1.0)
        pose_score = pose_result["movement_score"]
        motion_score = (flow_score * 0.6 + pose_score * 0.4)

        # Olay tipi belirle
        event_type = "none"
        is_significant = False

        if pose_result["gesture"] in ("hands_up", "hand_raise_left",
                                       "hand_raise_right"):
            if pose_result["gesture_confidence"] > 0.6:
                event_type = "gesture_excitement"
                is_significant = True

        if flow_result["significant_motion"]:
            if event_type == "none":
                event_type = "sudden_motion"
            is_significant = True

        return {
            "optical_flow": flow_result,
            "pose": pose_result,
            "motion_score": motion_score,
            "is_significant_event": is_significant,
            "event_type": event_type,
        }

    def reset(self):
        self.optical_flow.reset()
        self.pose_analyzer._prev_landmarks = None


# Singleton
motion_analyzer = MotionAnalyzer()
