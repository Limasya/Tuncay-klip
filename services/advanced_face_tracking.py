"""
Gelismis Face Tracking Kamera Kontrolu
opensource-clipping render_hybrid.py'den adaptasyon.
Deadzone tabanli kamera takibi, jitter threshold, scene-cut detection.
"""
import asyncio
import logging
import math
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Callable

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    _MP_AVAILABLE = True
except ImportError:
    _MP_AVAILABLE = False


@dataclass
class TrackingConfig:
    """Face tracking parametreleri."""
    step_detection: float = 0.25
    deadzone_ratio: float = 0.15
    smooth_factor: float = 0.30
    jitter_threshold: float = 5.0
    snap_threshold: float = 0.25
    scene_cut_threshold: int = 18
    face_detector: str = "mediapipe"
    static_crop: bool = False


@dataclass
class FaceData:
    """Tek bir frame'deki face detection sonucu."""
    time: float
    center_x: float
    center_y: float
    box: Optional[Tuple[float, float, float, float]] = None


@dataclass
class SmoothCameraState:
    """Yumusak kamera pozisyonu."""
    cx: float
    cy: float


class AdvancedFaceTracker:
    """
    Gelismis face tracking servisi.
    MediaPipe veya YOLO ile yuz algilar, deadzone tabanli kamera kontrolu uygular.
    """

    def __init__(self, config: Optional[TrackingConfig] = None):
        self.config = config or TrackingConfig()
        self._detector = None
        self._yolo_model = None

    def _ensure_detector(self) -> None:
        if self.config.face_detector == "yolo":
            if self._yolo_model is None:
                try:
                    from ultralytics import YOLO
                    self._yolo_model = YOLO("yolov8n-face.pt")
                except Exception as e:
                    logger.warning("YOLO yuklenemedi, MediaPipe'a donuluyor: %s", e)
                    self.config.face_detector = "mediapipe"

        if self.config.face_detector == "mediapipe" and self._detector is None:
            if not _MP_AVAILABLE:
                raise RuntimeError("MediaPipe yuklenemedi")
            model_url = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
            model_path = "models/blaze_face_short_range.tflite"
            import os, urllib.request
            os.makedirs("models", exist_ok=True)
            if not os.path.exists(model_path):
                urllib.request.urlretrieve(model_url, model_path)
            base_options = mp_python.BaseOptions(model_asset_path=model_path)
            self._detector = mp_vision.FaceDetector.create_from_options(
                mp_vision.FaceDetectorOptions(base_options=base_options, min_detection_confidence=0.5)
            )

    def detect_faces_frame(self, frame) -> Optional[FaceData]:
        """Tek bir frame'de en buyuk yuzu algila."""
        self._ensure_detector()

        if self.config.face_detector == "yolo" and self._yolo_model:
            results = self._yolo_model(frame, verbose=False)
            if results and len(results[0].boxes) > 0:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
                largest = boxes[areas.argmax()]
                cx = float(largest[0] + (largest[2] - largest[0]) / 2)
                cy = float(largest[1] + (largest[3] - largest[1]) / 2)
                return FaceData(time=0, center_x=cx, center_y=cy,
                                box=(float(largest[0]), float(largest[1]),
                                     float(largest[2]), float(largest[3])))
        elif self._detector:
            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            )
            results = self._detector.detect(mp_image)
            if results.detections:
                largest = max(results.detections,
                              key=lambda d: d.bounding_box.width * d.bounding_box.height)
                bb = largest.bounding_box
                cx = bb.origin_x + bb.width / 2
                cy = bb.origin_y + bb.height / 2
                return FaceData(time=0, center_x=cx, center_y=cy,
                                box=(bb.origin_x, bb.origin_y,
                                     bb.origin_x + bb.width, bb.origin_y + bb.height))
        return None

    def analyze_video(
        self,
        video_path: str,
        start_time: float = 0.0,
        end_time: float = 0.0,
    ) -> List[FaceData]:
        """Videoyu analiz et, frame bazli face data dondur."""
        if not _CV2_AVAILABLE:
            raise RuntimeError("OpenCV yuklenemedi")

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        video_duration = total_frames / fps if fps > 0 else 0
        if end_time <= 0:
            end_time = video_duration
        duration = end_time - start_time

        raw_data: List[FaceData] = []
        current_time = 0.0
        step = self.config.step_detection
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        default_cx = width / 2
        default_cy = height / 2

        while current_time <= duration:
            cap.set(cv2.CAP_PROP_POS_MSEC, (start_time + current_time) * 1000)
            ret, frame = cap.read()
            if not ret:
                break

            face = self.detect_faces_frame(frame)
            if face:
                face.time = current_time
                raw_data.append(face)
            else:
                raw_data.append(FaceData(time=current_time, center_x=default_cx, center_y=default_cy))
            current_time += step

        cap.release()
        return raw_data

    def compute_smooth_camera(
        self,
        raw_data: List[FaceData],
        frame_width: int,
        crop_width: int,
    ) -> List[SmoothCameraState]:
        """
        Deadzone tabanli yumusak kamera pozisyonlari hesapla.
        """
        cfg = self.config
        deadzone_px = crop_width * cfg.deadzone_ratio
        snap_px = frame_width * min(cfg.snap_threshold, 0.08)

        initial_cxs = [d.center_x for d in raw_data[:5]]
        cam_cx = statistics.median(initial_cxs) if initial_cxs else raw_data[0].center_x
        cam_cy = raw_data[0].center_y

        smooth_data: List[SmoothCameraState] = []
        for d in raw_data:
            face_cx = d.center_x
            face_cy = d.center_y

            if abs(face_cx - cam_cx) > snap_px:
                cam_cx = face_cx
            else:
                if face_cx > cam_cx + deadzone_px:
                    cam_cx += (face_cx - (cam_cx + deadzone_px)) * cfg.smooth_factor
                elif face_cx < cam_cx - deadzone_px:
                    cam_cx += (face_cx - (cam_cx - deadzone_px)) * cfg.smooth_factor

            cam_cy += (face_cy - cam_cy) * cfg.smooth_factor
            smooth_data.append(SmoothCameraState(cx=cam_cx, cy=cam_cy))

        return smooth_data

    def get_interpolated_position(
        self,
        smooth_data: List[SmoothCameraState],
        t: float,
        default_cx: float = 0,
        default_cy: float = 0,
    ) -> Tuple[float, float]:
        """Verilen zamanda lineer interpolasyon ile kamera pozisyonu."""
        if not smooth_data:
            return default_cx, default_cy

        step = self.config.step_detection
        idx = t / step
        i = int(idx)
        if i >= len(smooth_data) - 1:
            return smooth_data[-1].cx, smooth_data[-1].cy
        if i < 0:
            return smooth_data[0].cx, smooth_data[0].cy

        frac = idx - i
        s1 = smooth_data[i]
        s2 = smooth_data[i + 1]
        return s1.cx + (s2.cx - s1.cx) * frac, s1.cy + (s2.cy - s1.cy) * frac

    def detect_scene_cuts(self, raw_data: List[FaceData], frame_width: int) -> List[float]:
        """
        Yuz pozisyonundaki ani degisiklikleri tespit et (scene-cut).
        Snap threshold'u asan ani sicramalar dondurur.
        """
        cfg = self.config
        snap_px = frame_width * cfg.snap_threshold
        cuts: List[float] = []
        for i in range(1, len(raw_data)):
            dx = abs(raw_data[i].center_x - raw_data[i - 1].center_x)
            if dx > snap_px:
                cuts.append(raw_data[i].time)
        return cuts


async def track_faces_async(
    video_path: str,
    output_width: int = 1080,
    aspect: str = "9:16",
    config: Optional[TrackingConfig] = None,
) -> dict:
    """
    Async wrapper — video face tracking analizini thread'de calistirir.

    Returns:
        {
            "raw_data": [...],
            "smooth_data": [...],
            "scene_cuts": [...],
            "config": {...},
        }
    """
    tracker = AdvancedFaceTracker(config)

    def _run():
        raw = tracker.analyze_video(video_path)
        if not raw:
            return {"raw_data": [], "smooth_data": [], "scene_cuts": [], "config": {}}

        if aspect in ("9:16", "3:4", "4:5", "1:1"):
            crop_w = int(output_width * 9 / 16) if aspect == "9:16" else output_width
        else:
            crop_w = output_width

        frame_w = 1920
        smooth = tracker.compute_smooth_camera(raw, frame_w, crop_w)
        cuts = tracker.detect_scene_cuts(raw, frame_w)
        return {
            "raw_data": raw,
            "smooth_data": smooth,
            "scene_cuts": cuts,
            "config": {
                "step_detection": config.step_detection if config else 0.25,
                "deadzone_ratio": config.deadzone_ratio if config else 0.15,
                "smooth_factor": config.smooth_factor if config else 0.30,
                "snap_threshold": config.snap_threshold if config else 0.25,
            },
        }

    return await asyncio.to_thread(_run)
