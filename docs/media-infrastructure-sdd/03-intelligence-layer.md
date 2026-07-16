# Media Infrastructure SDD 03: Zeka Katmani (Intelligence Layer)

## Giris

Bu dokuman, Tuncay-klip sisteminin yapay zeka ve bilgisayar goruntusu katmanini tanimlar. Sistem, canli Kick/Twitch yayinlarindan alinan klip goruntulerini analiz ederek akilli duzenleme kararlari uretir. Mimari Python/FastAPI uzerine insa edilmistir; FFmpeg altyapi, OpenCV goruntu isleme ve ONNX Runtime (opsiyonel) ML model yurutme icin kullanilir.

**Zeka Katmani Bilesenleri:**

1. **Face Tracking Engine** — Yuz tespiti, takibi, kalite puani, kisilik kumelenmesi
2. **Intelligent Scene Detection** — Icerik-farkinda sahne degisimi algilama
3. **Content Analysis Pipeline** — Coklu-sinyal analiz fuzyonu (video+ses+chat+metadata)
4. **AI-Powered Edit Decision Engine** — Otomatik kesim noktasi, sure, ritim kararlari
5. **Quality Analysis** — Gorsel/issel kalite metrikleri ve platform uyumlulugu

**Render Pipeline'a Besleme:**

```ascii
[Stream Capture] -> [Intelligence Layer] -> [Edit Spec (ClipSpec)] -> [Render Pipeline]
                        |
                        v
               [ClipSpec olusturulur:
                time_range, speed, effects,
                color_grading, subtitles,
                beat_sync, emotion_arc,
                scene_detection kararlari]
```

Her analiz modulu `ClipSpec` modelindeki ilgili alanlari doldurur:
- `Face Tracking` → crop/reframe parametrelerini belirler
- `Scene Detection` → `SceneDetectionConfig`, `Transition`, `speed_segments` alanlarini doldurur
- `Content Analysis` → `composite_score`, `category`, `emotion_arc`, `beat_sync` alanlarini doldurur
- `Edit Decision Engine` → `time_range`, `effects`, `color_grading` alanlarini belirler
- `Quality Analysis` → Render sonrasi dogrulama ve platform profiling saglar

---
## 1. Face Tracking Engine (Yuz Takip Motoru)

### 1.1 Amac

Canli yayin kliplerinde yuzleri tespit etmek, kareler arasi takip etmek, yuz kalitesini puanlamak ve ayni kisiyi farkli kesitlerde taniyarak kamerayi yonlendirmek. Bu modul, ozellikle dikey video (9:16) otomatik cerceveleme ve yuz-odakli krop icin kritiktir.

### 1.2 Mimari

```ascii
[Frame N] --> [FaceDetector (OpenCV DNN / ONNX)]
           --> [FaceTracker (IoU + Kalman Filter)]
           --> [FaceLandmarker (MediaPipe / ONNX)]
           --> [FaceQualityScorer]
           --> [FaceClustering (cosine similarity)]
           --> [FaceCropFollowEngine]
```

**Tespit Stratejisi:**
- **Every-N frame**: Her 3-5 karede bir tam tespit (yavas model)
- **Aradaki kareler**: Kalman filter ile takip (hizli)
- **Fallback**: Tespit basarisizsa optik akis tabanli takip

### 1.3 Veri Yapilari (Python)

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Tuple
from enum import Enum
import numpy as np


class FaceLandmark(BaseModel):
    """Yuz nokta bulut modeli.
    
    68-point (dlib standard) veya 478-point (MediaPipe) destegi.
    """
    points_68: Optional[List[Tuple[float, float]]] = None
    points_478: Optional[List[Tuple[float, float]]] = None
    left_eye: Optional[List[Tuple[float, float]]] = None
    right_eye: Optional[List[Tuple[float, float]]] = None
    nose_tip: Optional[Tuple[float, float]] = None
    mouth_contour: Optional[List[Tuple[float, float]]] = None
    face_oval: Optional[List[Tuple[float, float]]] = None


class FaceQuality(BaseModel):
    """Yuz kalite puanlari. Her skor [0, 1] araligindadir. 1 = en iyi."""
    blur_score: float = Field(default=1.0, ge=0.0, le=1.0)
    angle_score: float = Field(default=1.0, ge=0.0, le=1.0)
    occlusion_score: float = Field(default=1.0, ge=0.0, le=1.0)
    size_score: float = Field(default=0.5, ge=0.0, le=1.0)
    brightness_score: float = Field(default=1.0, ge=0.0, le=1.0)
    overall_quality: float = Field(default=1.0, ge=0.0, le=1.0)


class FaceTrack(BaseModel):
    """Tek bir yuzun kareler arasi takip kaydi."""
    track_id: int
    first_seen: float
    last_seen: float
    bbox_history: List[Tuple[float, float, float, float]] = Field(default_factory=list)
    landmark_history: List[Optional[FaceLandmark]] = Field(default_factory=list)
    quality_history: List[Optional[FaceQuality]] = Field(default_factory=list)
    max_quality: FaceQuality = Field(default_factory=FaceQuality)
    total_frames: int = 0
    track_confidence: float = 0.0
    is_active: bool = True
    dominant_emotion: str = "neutral"
    emotion_history: List[Tuple[str, float]] = Field(default_factory=list)


class FaceCluster(BaseModel):
    """Ayni kisiye ait yuz takipleri."""
    cluster_id: int
    identity_label: Optional[str] = None
    face_tracks: List[FaceTrack] = Field(default_factory=list)
    embedding: Optional[np.ndarray] = None
    screen_time: float = 0.0
    avg_quality: float = 0.0
    is_primary: bool = False

    def merge_track(self, track: FaceTrack) -> None: ...


class FaceDetectionConfig(BaseModel):
    """Yuz tespit ve takip yapilandirmasi."""
    detection_interval: int = 3
    min_detection_confidence: float = 0.5
    min_tracking_confidence: float = 0.6
    max_track_age: float = 2.0
    iou_threshold: float = 0.4
    quality_weight_blur: float = 0.3
    quality_weight_angle: float = 0.25
    quality_weight_occlusion: float = 0.25
    quality_weight_size: float = 0.2
    enable_landmarks: bool = True
    enable_emotion: bool = True
    model_path: Optional[str] = "models/face_detection.onnx"
    landmark_model_path: Optional[str] = "models/face_landmark.onnx"
```
### 1.4 Algoritmalar

**1.4.1 Coklu-Yuz Tespiti (Multi-Face Detection)**

```python
import cv2
import numpy as np

class FaceDetector:
    """OpenCV DNN (SSD) veya ONNX modeli ile yuz tespiti."""

    def __init__(self, config: FaceDetectionConfig):
        self.config = config
        self._net = None
        self._load_model()

    def _load_model(self):
        if self.config.model_path and Path(self.config.model_path).exists():
            import onnxruntime as ort
            self._session = ort.InferenceSession(self.config.model_path)
            self._input_name = self._session.get_inputs()[0].name
            self._use_onnx = True
        else:
            self._net = cv2.dnn.readNetFromCaffe(
                "models/deploy.prototxt",
                "models/res10_300x300_ssd_iter_140000.caffemodel"
            )
            self._use_onnx = False

    def detect(self, frame: np.ndarray) -> List[Tuple[float, float, float, float, float]]:
        """Yuzleri tespit eder. Returns: [(x1, y1, x2, y2, confidence)] normalized."""
        h, w = frame.shape[:2]

        if self._use_onnx:
            blob = cv2.dnn.blobFromImage(
                cv2.resize(frame, (640, 640)), 1.0/255.0, (640, 640),
                swapRB=True, crop=False
            )
            outputs = self._session.run(None, {self._input_name: blob})
            detections = outputs[0][0]
        else:
            blob = cv2.dnn.blobFromImage(
                cv2.resize(frame, (300, 300)), 1.0, (300, 300),
                (104.0, 177.0, 123.0)
            )
            self._net.setInput(blob)
            detections = self._net.forward()[0, 0]

        faces = []
        for i in range(detections.shape[0]):
            confidence = float(detections[i, 2])
            if confidence < self.config.min_detection_confidence:
                continue
            box = detections[i, 3:7]
            x1, y1, x2, y2 = box
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(1, x2), min(1, y2)
            faces.append((x1, y1, x2, y2, confidence))
        return faces
```

**1.4.2 Kalman Filter ile Yuz Takibi (Face Tracking)**

```python
class FaceTracker:
    """IoU + Kalman filter ile kareler arasi yuz takibi."""

    def __init__(self, config: FaceDetectionConfig):
        self.config = config
        self.tracks: Dict[int, FaceTrack] = {}
        self._next_id = 0
        self._kalman_filters: Dict[int, cv2.KalmanFilter] = {}

    def _create_kalman(self) -> cv2.KalmanFilter:
        """8-boyutlu Kalman state: (cx, cy, w, h, vx, vy, vw, vh)"""
        kf = cv2.KalmanFilter(8, 4)
        kf.measurementMatrix = np.eye(4, 8, dtype=np.float32)
        kf.transitionMatrix = np.array([
            [1,0,0,0,1,0,0,0], [0,1,0,0,0,1,0,0],
            [0,0,1,0,0,0,1,0], [0,0,0,1,0,0,0,1],
            [0,0,0,0,1,0,0,0], [0,0,0,0,0,1,0,0],
            [0,0,0,0,0,0,1,0], [0,0,0,0,0,0,0,1],
        ], dtype=np.float32)
        kf.processNoiseCov = np.eye(8, dtype=np.float32) * 1e-3
        kf.measurementNoiseCov = np.eye(4, dtype=np.float32) * 1e-1
        return kf

    def update(self, detections: List[Tuple], timestamp: float,
               landmarks: Dict[int, FaceLandmark] = None,
               qualities: Dict[int, FaceQuality] = None) -> Dict[int, FaceTrack]:
        """Hungarian algorithm ile atama + Kalman update."""
        predicted_boxes = {}
        for tid, kf in self._kalman_filters.items():
            predicted = kf.predict()
            cx, cy, w, h = predicted[:4]
            predicted_boxes[tid] = (cx - w/2, cy - h/2, cx + w/2, cy + h/2)

        cost_matrix = np.zeros((len(predicted_boxes), len(detections)))
        for i, (tid, pbox) in enumerate(predicted_boxes.items()):
            for j, dbox in enumerate(detections):
                cost_matrix[i, j] = 1 - self._iou(pbox, dbox[:4])

        from scipy.optimize import linear_sum_assignment
        row_ind, col_ind = linear_sum_assignment(cost_matrix)

        assignments = {}
        for i, j in zip(row_ind, col_ind):
            if cost_matrix[i, j] < (1 - self.config.iou_threshold):
                tid = list(predicted_boxes.keys())[i]
                assignments[tid] = detections[j]

        updated = {}
        for tid, det in assignments.items():
            x1, y1, x2, y2, conf = det
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            w, h = x2 - x1, y2 - y1
            self._kalman_filters[tid].correct(np.array([cx, cy, w, h], dtype=np.float32))
            self.tracks[tid].bbox_history.append((x1, y1, w, h))
            self.tracks[tid].last_seen = timestamp
            self.tracks[tid].total_frames += 1
            self.tracks[tid].track_confidence = min(1.0, self.tracks[tid].total_frames / 30)

            if landmarks and tid in landmarks:
                self.tracks[tid].landmark_history.append(landmarks[tid])
            if qualities and tid in qualities:
                self.tracks[tid].quality_history.append(qualities[tid])
                if qualities[tid].overall_quality > self.tracks[tid].max_quality.overall_quality:
                    self.tracks[tid].max_quality = qualities[tid]
            updated[tid] = self.tracks[tid]

        # Yeni track'ler (atanmayan detections)
        assigned_dets = set(assignments.values())
        for det in detections:
            if det not in assigned_dets:
                tid = self._next_id; self._next_id += 1
                x1, y1, x2, y2, conf = det
                w, h = x2 - x1, y2 - y1
                track = FaceTrack(track_id=tid, first_seen=timestamp, last_seen=timestamp,
                                  bbox_history=[(x1, y1, w, h)], total_frames=1,
                                  track_confidence=0.3, is_active=True)
                self.tracks[tid] = track
                self._kalman_filters[tid] = self._create_kalman()
                kf = self._kalman_filters[tid]
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                kf.statePost = np.array([cx, cy, w, h, 0, 0, 0, 0], dtype=np.float32)
                updated[tid] = track

        # Yaslandirma/sonlandirma
        active = set(updated.keys())
        for tid in list(self.tracks.keys()):
            if tid not in active:
                age = timestamp - self.tracks[tid].last_seen
                if age > self.config.max_track_age:
                    self.tracks[tid].is_active = False

        return updated

    def _iou(self, box_a: Tuple, box_b: Tuple) -> float:
        xa1, ya1, xa2, ya2 = box_a
        xb1, yb1, xb2, yb2 = box_b
        xi1 = max(xa1, xb1); yi1 = max(ya1, yb1)
        xi2 = min(xa2, xb2); yi2 = min(ya2, yb2)
        inter = max(0, xi2 - xi1) * max(0, yi2 - yi1)
        area_a = (xa2 - xa1) * (ya2 - ya1)
        area_b = (xb2 - xb1) * (yb2 - yb1)
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0
```
**1.4.3 Yuz Kalite Puani (Face Quality Scoring)**

```python
class FaceQualityScorer:
    """Yuz kalitesini 4 boyutta puanlar ve bilesik skor uretir."""

    def __init__(self, config: FaceDetectionConfig):
        self.config = config

    def score(self, face_roi: np.ndarray, bbox: Tuple,
              landmarks: Optional[FaceLandmark] = None) -> FaceQuality:
        gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)

        # Blur: Laplacian variance
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        blur_score = min(1.0, laplacian_var / 300.0)

        # Angle: landmark simetrisi
        angle_score = 1.0
        if landmarks and landmarks.points_68 and len(landmarks.points_68) >= 68:
            left_eye = np.mean(landmarks.points_68[36:42], axis=0)
            right_eye = np.mean(landmarks.points_68[42:48], axis=0)
            nose = landmarks.points_68[30]
            eye_mid = (left_eye + right_eye) / 2
            dx = nose[0] - eye_mid[0]
            eye_dist = np.linalg.norm(right_eye - left_eye)
            angle_score = max(0.0, 1.0 - abs(dx) / (eye_dist * 0.5))

        # Occlusion: convex hull vs contour area
        occlusion_score = 1.0
        if landmarks and landmarks.face_oval:
            oval = np.array(landmarks.face_oval, dtype=np.int32)
            if cv2.contourArea(oval) > 0:
                hull = cv2.convexHull(oval)
                hull_area = cv2.contourArea(hull)
                oval_area = cv2.contourArea(oval)
                occlusion_score = min(1.0, oval_area / max(hull_area, 1))

        # Size: face area / frame area
        x1, y1, x2, y2 = bbox
        face_area = (x2 - x1) * (y2 - y1)
        size_score = min(1.0, face_area * 4)

        # Brightness
        mean_brightness = np.mean(gray) / 255.0
        brightness_score = 1.0 - abs(mean_brightness - 0.5) * 2

        overall = (self.config.quality_weight_blur * blur_score +
                   self.config.quality_weight_angle * angle_score +
                   self.config.quality_weight_occlusion * occlusion_score +
                   self.config.quality_weight_size * size_score)

        return FaceQuality(blur_score=round(blur_score, 4),
                           angle_score=round(angle_score, 4),
                           occlusion_score=round(occlusion_score, 4),
                           size_score=round(size_score, 4),
                           brightness_score=round(brightness_score, 4),
                           overall_quality=round(min(1.0, overall * (0.8 + 0.2 * brightness_score)), 4))
```

**1.4.4 Yuz Kumeleme (Face Clustering)**

```python
class FaceClusterEngine:
    """Ayni kisiye ait yuz track'lerini cosine similarity ile kumeler."""

    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold
        self.clusters: List[FaceCluster] = []
        self._next_cluster_id = 0

    def extract_embedding(self, face_roi: np.ndarray) -> np.ndarray:
        """128-boyutlu embedding (ArcFace/ONNX)."""
        if not hasattr(self, '_embedding_model'):
            return np.random.randn(128).astype(np.float32)
        blob = cv2.dnn.blobFromImage(
            cv2.resize(face_roi, (112, 112)), 1.0/255.0, (112, 112),
            swapRB=True, mean=(0.5, 0.5, 0.5), scale=1.0/0.5
        )
        embedding = self._embedding_model.run(None, {'input': blob})[0][0]
        return embedding / np.linalg.norm(embedding)

    def assign_track_to_cluster(self, track: FaceTrack, embedding: np.ndarray) -> int:
        best_cluster, best_similarity = None, self.threshold
        for cluster in self.clusters:
            if cluster.embedding is not None:
                sim = np.dot(embedding, cluster.embedding)
                sim /= (np.linalg.norm(embedding) * np.linalg.norm(cluster.embedding) + 1e-8)
                if sim > best_similarity:
                    best_similarity = sim
                    best_cluster = cluster

        if best_cluster is not None:
            best_cluster.face_tracks.append(track)
            n = len(best_cluster.face_tracks)
            best_cluster.embedding = (best_cluster.embedding * (n - 1) + embedding) / n
            best_cluster.screen_time += (track.last_seen - track.first_seen)
            return best_cluster.cluster_id
        else:
            cid = self._next_cluster_id; self._next_cluster_id += 1
            self.clusters.append(FaceCluster(cluster_id=cid, face_tracks=[track],
                                              embedding=embedding,
                                              screen_time=track.last_seen - track.first_seen))
            return cid
```

**1.4.5 Yuz-Odakli Krop Takibi (Face Crop Following)**

```python
class FaceCropFollowEngine:
    """Ana konusmacinin yuzunu dikey videoda merkezde tutar."""

    def __init__(self, frame_size: Tuple[int, int], target_aspect: float = 9.0/16.0):
        self.frame_w, self.frame_h = frame_size
        self.target_aspect = target_aspect
        self._current_crop = None
        self._velocity = np.array([0.0, 0.0])
        self._max_velocity = frame_size[0] * 0.15  # %15/sn

    def compute_crop(self, primary_face_bbox: Tuple[float, float, float, float],
                     dt: float) -> Tuple[int, int, int, int]:
        x1, y1, x2, y2 = primary_face_bbox
        face_cx = (x1 + x2) / 2 * self.frame_w
        crop_w = int(self.frame_h * self.target_aspect)
        crop_h = self.frame_h
        target_x = int(face_cx - crop_w / 2)
        target_x = max(0, min(target_x, self.frame_w - crop_w))

        if self._current_crop is None:
            self._current_crop = (target_x, 0, crop_w, crop_h)
            return self._current_crop

        # Velocity clamping
        dx = target_x - self._current_crop[0]
        max_dx = self._max_velocity * dt
        dx = max(-max_dx, min(max_dx, dx))
        new_x = int(max(0, min(self._current_crop[0] + dx, self.frame_w - crop_w)))

        self._current_crop = (new_x, 0, crop_w, crop_h)
        return self._current_crop
```
### 1.5 API Sozlesmesi

```python
class FaceTrackingService:
    """Yuz takip servisi - modulun disa acik API'si."""

    async def process_frame(self, frame: np.ndarray, timestamp: float) -> Dict:
        """
        Returns:
        {
            "tracks": {track_id: {"bbox": [x1,y1,x2,y2], "landmarks": {...},
                         "quality": {...}, "emotion": "happy",
                         "cluster_id": 0, "is_primary": True}},
            "clusters": {cluster_id: {"identity_label": "streamer", ...}},
            "primary_face": {"track_id": 0, "bbox": [...], "crop_follow": [x,y,w,h]},
            "stats": {"total_tracks": 3, "active_tracks": 2, "total_clusters": 1}
        }
        """
        ...

    async def get_best_face_thumbnail(self) -> Optional[np.ndarray]: ...
    def get_primary_cluster(self) -> Optional[FaceCluster]: ...
```

### 1.6 Render Pipeline Entegresyonu

```ascii
[FaceTrackingService.process_frame()]
    |
    v
[FaceCropFollowEngine.compute_crop()] -> crop_rect
    |
    v
[ClipSpec'e yansitma]:
    - aspect_ratio = PORTRAIT_9_16
    - FFmpeg crop filter: crop=crop_w:crop_h:crop_x:crop_y
    - thumbnail.time_point = en iyi yuz kalitesi ani
    - lower_thirds entries[i].name = cluster.identity_label
    - emotion_arc.segments = emotion_history
```

### 1.7 Performans Dar Bogazlari ve Cozumleri

| Dar Bogaz | Belirti | Cozum |
|-----------|---------|-------|
| ONNX model inference (~15ms) | Frame drop | Her N karede calistir, arada Kalman |
| Coklu yuz tespiti (5+ kisi) | CPU/GPU doygunlugu | MediaPipe fallback (daha hafif) |
| Embedding karsilastirma (N^2) | Kumeleme yavaslari | FAISS ile ANN indeksleme |
| Yuz landmark hesaplama | Ek 5-8ms | Sadece kalite puani gerektiginde |

**Onerilen Cozum:** Tespit her 3 karede bir ONNX (veya MediaPipe), embedding her 10 karede bir (veya sahne degisiminde), landmark sadece kalite puani gerektiginde, kumeleme sadece track sonlandiginda (offline).

---
## 2. Intelligent Scene Detection (Akilli Sahne Algilama)

### 2.1 Amac

Video icerisindeki sahne gecislerini tespit etmek, her sahneyi siniflandirmak ve skorlamak. Bu bilgiler edit kararlari (kesim noktalari, efekt atama, hiz degisimi) icin temel olusturur.

### 2.2 Mimari

```ascii
[Frame N-1, Frame N] --> [Histogram Comparison]
                      --> [SSIM]
                      --> [ML Classifier (opsiyonel)]
                      --> [Boundary Refinement]
                      --> [Scene Scoring]
                      --> [Transition Type Prediction]
```

### 2.3 Veri Yapilari (Python)

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Tuple
from enum import Enum


class SceneType(str, Enum):
    CUT = "cut"                       # Ani kesim
    FADE_IN = "fade_in"               # Acilis kararmasi
    FADE_OUT = "fade_out"             # Kapanis kararmasi
    DISSOLVE = "dissolve"             # Gecisim yumusak
    WIPE = "wipe"                     # Silme efekti
    MATCH_CUT = "match_cut"           # Gorsel benzerlikle kesim
    JUMP_CUT = "jump_cut"             # Atlama kesimi
    HARD_FLASH = "hard_flash"         # Parlama ile gecis
    UNKNOWN = "unknown"


class SceneBoundary(BaseModel):
    """Sahne siniri bilgisi."""
    frame_index: int
    timestamp: float
    confidence: float = Field(ge=0.0, le=1.0)
    transition_type: SceneType = SceneType.UNKNOWN
    histogram_distance: float = 0.0
    ssim_score: float = 0.0
    motion_magnitude: float = 0.0
    ml_score: float = 0.0

    @property
    def is_hard_cut(self) -> bool:
        return self.transition_type == SceneType.CUT


class SceneScore(BaseModel):
    """Sahne kalite/oncelik puani."""
    scene_index: int
    start: float
    end: float
    duration: float
    avg_motion: float = 0.0
    avg_brightness: float = 0.0
    avg_saturation: float = 0.0
    contrast_score: float = 0.0
    face_presence: float = 0.0
    audio_energy: float = 0.0
    audio_peak: float = 0.0
    chat_intensity: float = 0.0
    emotion_valence: float = 0.0
    emotion_arousal: float = 0.0
    interest_score: float = Field(default=0.0, ge=0.0, le=1.0)
    is_highlight: bool = False


class SceneDetectionResult(BaseModel):
    """Tum video icin sahne algilama sonucu."""
    boundaries: List[SceneBoundary] = Field(default_factory=list)
    scenes: List[SceneScore] = Field(default_factory=list)
    total_scenes: int = 0
    avg_scene_duration: float = 0.0
    detection_method: str = "hybrid"


class SceneDetectionConfig(BaseModel):
    """Sahne algilama yapilandirmasi."""
    histogram_method: str = "chi_squared"
    histogram_bins: int = 64
    ssim_threshold: float = 0.7
    cut_threshold: float = 0.3
    min_scene_duration: float = 0.5
    boundary_refinement_window: int = 5
    enable_ml_classifier: bool = False
    ml_model_path: Optional[str] = None
    adaptive_threshold: bool = True
```
### 2.4 Algoritmalar

**2.4.1 Histogram Karsilastirma**

```python
class HistogramComparator:
    """Kareler arasi histogram mesafesi ile kesim tespiti."""

    def __init__(self, bins: int = 64, method: str = "chi_squared"):
        self.bins = bins
        self.method = method

    def compare(self, frame_a: np.ndarray, frame_b: np.ndarray) -> float:
        """
        Histogram mesafesi [0, 1]. 0 = ayni, 1 = farkli.

        Yontemler:
        - chi_squared: x^2(a,b) = sum((ai-bi)^2 / (ai+bi))
        - correlation: cor(a,b) normalized [-1,1] -> [0,1]
        - intersection: I(a,b) = sum(min(ai,bi)) -> [0,1]
        """
        import cv2

        h, w = frame_a.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.rectangle(mask, (int(w*0.05), int(h*0.05)),
                      (int(w*0.95), int(h*0.95)), 255, -1)

        hist_a = cv2.calcHist([frame_a], [0, 1, 2], mask,
                               [self.bins]*3, [0, 256]*3)
        hist_b = cv2.calcHist([frame_b], [0, 1, 2], mask,
                               [self.bins]*3, [0, 256]*3)
        cv2.normalize(hist_a, hist_a, 0, 1, cv2.NORM_MINMAX)
        cv2.normalize(hist_b, hist_b, 0, 1, cv2.NORM_MINMAX)

        methods = {"chi_squared": cv2.HISTCMP_CHISQR,
                   "correlation": cv2.HISTCMP_CORREL,
                   "intersection": cv2.HISTCMP_INTERSECT}
        method = methods.get(self.method, cv2.HISTCMP_CHISQR)
        distance = cv2.compareHist(hist_a, hist_b, method)

        if self.method == "chi_squared":
            return min(1.0, distance / (self.bins ** 3 * 0.1))
        elif self.method == "correlation":
            return 1.0 - max(-1.0, min(1.0, distance))
        elif self.method == "intersection":
            return 1.0 - distance
        return distance
```

**2.4.2 SSIM ile Yapisal Benzerlik**

```python
class SSIMAnalyzer:
    """Structural Similarity Index ile yapisal karsilastirma."""

    def compute(self, frame_a: np.ndarray, frame_b: np.ndarray) -> float:
        """
        SSIM = (2*mu_x*mu_y + C1)(2*sigma_xy + C2) /
              (mu_x^2 + mu_y^2 + C1)(sigma_x^2 + sigma_y^2 + C2)
        Returns [0, 1]. 1 = tamamen ayni.
        """
        gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
        gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)
        from skimage.metrics import structural_similarity
        score, _ = structural_similarity(gray_a, gray_b, full=True)
        return float(score)

    def compute_block_ssim(self, frame_a: np.ndarray, frame_b: np.ndarray,
                           grid: Tuple[int, int] = (4, 4)) -> np.ndarray:
        """4x4 blok tabanli SSIM haritasi."""
        h, w = frame_a.shape[:2]
        bh, bw = h // grid[0], w // grid[1]
        scores = np.zeros(grid)
        for i in range(grid[0]):
            for j in range(grid[1]):
                y1, y2 = i*bh, (i+1)*bh
                x1, x2 = j*bw, (j+1)*bw
                block_a = cv2.cvtColor(frame_a[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
                block_b = cv2.cvtColor(frame_b[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
                scores[i, j] = structural_similarity(block_a, block_b)
        return scores
```

**2.4.3 ML Tabanli Sahne Siniflandirma (Opsiyonel)**

```python
class SceneMLClassifier:
    """
    ONNX ile sahne gecisi tipi siniflandirma.

    Model girisleri (20 boyut):
    - Histogram distance (1)
    - SSIM score (1)
    - Motion magnitude (1)
    - HSV histogram distance (1)
    - Edge histogram distance (1)
    - Block-wise SSIM (4x4 = 16)

    Cikis: SceneType (8 sinif)
    """

    def __init__(self, model_path: str):
        import onnxruntime as ort
        self.session = ort.InferenceSession(model_path)
        self.input_name = self.session.get_inputs()[0].name

    def predict(self, features: np.ndarray) -> Tuple[SceneType, float]:
        features = features.reshape(1, -1).astype(np.float32)
        outputs = self.session.run(None, {self.input_name: features})
        probs = outputs[0][0]
        class_id = int(np.argmax(probs))
        type_map = [SceneType.CUT, SceneType.FADE_IN, SceneType.FADE_OUT,
                    SceneType.DISSOLVE, SceneType.WIPE, SceneType.MATCH_CUT,
                    SceneType.JUMP_CUT, SceneType.HARD_FLASH]
        return type_map[class_id], float(probs[class_id])
```
**2.4.4 Sinir Iyilestirme (Boundary Refinement)**

```python
class BoundaryRefiner:
    """Kesim noktasi dogrulugunu artirmak icin ince ayar."""

    def __init__(self, config: SceneDetectionConfig):
        self.config = config

    def refine(self, raw_boundaries: List[SceneBoundary],
               frames: List[np.ndarray], timestamps: List[float]) -> List[SceneBoundary]:
        if not raw_boundaries:
            return []

        refined = []
        window = self.config.boundary_refinement_window
        hc = HistogramComparator(self.config.histogram_bins, self.config.histogram_method)

        for boundary in raw_boundaries:
            idx = boundary.frame_index
            start = max(0, idx - window)
            end = min(len(frames) - 1, idx + window)

            best_idx, best_distance = idx, boundary.histogram_distance
            for j in range(start, end - 1):
                dist = hc.compare(frames[j], frames[j + 1])
                if dist > best_distance:
                    best_distance = dist
                    best_idx = j

            if best_distance < self.config.cut_threshold:
                continue

            refined.append(SceneBoundary(frame_index=best_idx, timestamp=timestamps[best_idx],
                                          confidence=min(1.0, best_distance * 2),
                                          transition_type=boundary.transition_type,
                                          histogram_distance=best_distance))

        # Minimum sure filtresi
        result = []
        for b in refined:
            if not result or b.timestamp - result[-1].timestamp >= self.config.min_scene_duration:
                result.append(b)
        return result
```

**2.4.5 Sahne Skorlama ve Siralama**

```python
class SceneScorer:
    """Her sahneyi cesitli metriklerle puanlar ve highlight adaylarini belirler."""

    WEIGHTS = {"motion": 0.20, "face": 0.25, "audio": 0.20,
               "emotion": 0.15, "chat": 0.10, "visual": 0.10}

    def score_scene(self, scene: SceneScore,
                    motion_profile: List[float], face_profile: List[float],
                    audio_profile: List[float], emotion_profile: List[Dict],
                    chat_profile: List[float]) -> SceneScore:
        scene.avg_motion = float(np.mean(motion_profile)) if motion_profile else 0.0
        scene.face_presence = float(np.mean(face_profile)) if face_profile else 0.0
        scene.audio_peak = float(np.max(audio_profile)) if audio_profile else 0.0
        scene.audio_energy = float(np.mean(audio_profile)) if audio_profile else 0.0

        if emotion_profile:
            scene.emotion_valence = float(np.mean([e.get("valence", 0) for e in emotion_profile]))
            scene.emotion_arousal = float(np.mean([e.get("arousal", 0) for e in emotion_profile]))
        if chat_profile:
            scene.chat_intensity = float(np.mean(chat_profile))

        score = (self.WEIGHTS["motion"] * scene.avg_motion +
                 self.WEIGHTS["face"] * scene.face_presence +
                 self.WEIGHTS["audio"] * scene.audio_peak +
                 self.WEIGHTS["emotion"] * scene.emotion_arousal +
                 self.WEIGHTS["chat"] * scene.chat_intensity +
                 self.WEIGHTS["visual"] * scene.contrast_score)
        scene.interest_score = min(1.0, max(0.0, score))
        scene.is_highlight = scene.interest_score > 0.65
        return scene
```

### 2.5 API Sozlesmesi

```python
class SceneDetectionService:
    """Sahne algilama servisi."""

    async def analyze(self, video_path: str,
                      config: Optional[SceneDetectionConfig] = None) -> SceneDetectionResult:
        """1. Frame'leri oku (her N karede bir), 2. Histogram+SSIM, 3. ML (varsa),
           4. Boundary refinement, 5. Scene score, 6. Highlight belirleme."""
        ...

    async def get_best_scene_thumbnails(self, n: int = 5) -> List[Tuple[float, float]]: ...
    def score_scenes(self, result: SceneDetectionResult) -> SceneDetectionResult: ...
    def get_scene_edl(self, result: SceneDetectionResult, max_duration: float = 60.0
                      ) -> List[Tuple[float, float]]: ...
```

### 2.6 Render Pipeline Entegresyonu

```ascii
[SceneDetectionService.analyze()]
    |
    v
[ClipSpec'e yansitma]:
    - scene_detection.enabled = True
    - scene_detection.threshold, min_scene_duration
    - scene_detection.highlight_reel = True
    - transition_between.type = SceneType -> TransitionType donusumu
    - speed_segments = kisa sahne hizlanma / uzun sahne yavaslatma
```

FFmpeg entegrasyonu:
```bash
# Scene detection ile kesim noktalari
ffmpeg -i input.mp4 -vf "select='gt(scene,0.3)',showinfo" -f null -

# Sahne bazli hiz
setpts=1.5*PTS  # kisa sahneler hizlanir
setpts=0.7*PTS  # uzun sahneler yavaslar
```

### 2.7 Performans Dar Bogazlari ve Cozumleri

| Dar Bogaz | Belirti | Cozum |
|-----------|---------|-------|
| Her karede histogram | Agir CPU | Her 2. karede analiz |
| SSIM hesaplama (~5ms) | Yavas | Sadece boundary adaylarinda |
| ML inference (~10ms) | GPU gerektirir | ONNX+CUDA, async queue |
| Cok sayida kucuk sahne | Gereksiz gecis | Min sure filtresi (0.5s) |

---
## 3. Content Analysis Pipeline (Icerik Analizi Pipelinei)

### 3.1 Amac

Birden fazla sinyali (video, ses, chat, metadata) es zamanli analiz ederek birlestirmek, heyecan/ilgi seviyesini zaman icinde izlemek ve highlight anlarini tespit etmek.

### 3.2 Mimari

```ascii
[Video Frames]  --> [Face/Emotion Analysis]
                 --> [Motion Analysis]
                 --> [Scene Change Analysis]

[Audio Stream]  --> [Energy Profile]
                 --> [Spectral Analysis]
                 --> [VAD / Speech Detection]

[Chat Stream]   --> [Sentiment Analysis]
                 --> [Message Volume]
                 --> [Emoji/Keyword Detection]

[Metadata]      --> [Stream Events]
                 --> [Game State]
                 --> [Donations/Subs]

                        |
                        v
              [Multi-Signal Fusion Engine]
                        |
                        v
              [Excitement Score (temporal)]
                        |
                        v
              [Highlight Detection]
```

### 3.3 Veri Yapilari (Python)

```python
class ContentSignal(BaseModel):
    """Tek bir kaynaktan gelen analiz sinyali."""
    source: str                    # "face", "motion", "audio", "chat", "scene"
    timestamp: float
    value: float                   # Normalize [0, 1]
    confidence: float = 1.0
    metadata: Dict = Field(default_factory=dict)


class AnalysisFrame(BaseModel):
    """Bir zaman dilimindeki tum analiz sinyalleri."""
    timestamp: float
    frame_index: int = 0
    face_score: float = 0.0
    motion_score: float = 0.0
    audio_score: float = 0.0
    chat_score: float = 0.0
    scene_change: float = 0.0
    composite_score: float = 0.0
    is_event: bool = False
    event_type: Optional[str] = None


class ExcitementScore(BaseModel):
    """Zaman icinde heyecan skoru."""
    time: float
    score: float                   # [0, 1]
    triggered_by: List[str] = Field(default_factory=list)


class HighlightWindow(BaseModel):
    """Bir highlight penceresi."""
    start: float
    end: float
    peak_score: float
    avg_score: float
    duration: float
    category: str = "general"
    triggers: List[ContentSignal] = Field(default_factory=list)
    is_selected: bool = False


class ContentAnalysisConfig(BaseModel):
    """Icerik analizi yapilandirmasi."""
    window_size: float = 3.0
    hop_size: float = 0.5
    min_highlight_duration: float = 2.0
    max_highlight_duration: float = 30.0
    weights: Dict[str, float] = Field(default_factory=lambda: {
        "face": 0.25, "motion": 0.20, "audio": 0.25,
        "chat": 0.15, "scene": 0.15,
    })
    event_threshold: float = 0.6
    highlight_threshold: float = 0.7
    cooldown: float = 8.0
    context_window: float = 30.0
    enable_chat: bool = True
    enable_audio: bool = True
```
### 3.4 Algoritmalar

**3.4.1 Coklu-Sinyal Fuzyon Motoru**

```python
class MultiSignalFusionEngine:
    """Farkli kaynaklardan gelen sinyalleri birlestirir."""

    def __init__(self, config: ContentAnalysisConfig):
        self.config = config
        self._ema_score = 0.0
        self._ema_alpha = 0.3
        self._last_event_time = 0.0

    def fuse(self, frame: AnalysisFrame) -> AnalysisFrame:
        """Sinyalleri birlestir: composite = sum(w_i * signal_i)."""
        w = self.config.weights
        composite = (w["face"] * frame.face_score + w["motion"] * frame.motion_score +
                     w["audio"] * frame.audio_score + w["chat"] * frame.chat_score +
                     w["scene"] * frame.scene_change)
        frame.composite_score = min(1.0, composite)

        # EMA smoothing
        self._ema_score = (self._ema_alpha * frame.composite_score +
                           (1 - self._ema_alpha) * self._ema_score)

        # Event detection
        if (frame.composite_score >= self.config.event_threshold and
            frame.timestamp - self._last_event_time >= self.config.cooldown):
            frame.is_event = True
            frame.event_type = self._classify_event(frame)
            self._last_event_time = frame.timestamp

        return frame

    def _classify_event(self, frame: AnalysisFrame) -> str:
        scores = {"big_moment": frame.face_score + frame.audio_score,
                  "action": frame.motion_score + frame.audio_score,
                  "chat_moment": frame.chat_score,
                  "scene_shift": frame.scene_change}
        return max(scores, key=scores.get)
```

**3.4.2 Duygu Arki (Emotion Arc) Takibi**

```python
class EmotionArcTracker:
    """Stream boyunca duygu degisimini Valence-Arousal modeli ile izler."""

    def __init__(self, window: float = 30.0):
        self.window = window
        self.history: List[Dict] = []

    def update(self, timestamp: float, emotions: Dict[str, float]) -> Dict:
        valence_map = {"happy": 0.8, "surprise": 0.3, "neutral": 0.0,
                       "sad": -0.7, "angry": -0.6, "fear": -0.5, "disgust": -0.6}
        arousal_map = {"happy": 0.6, "surprise": 0.8, "neutral": 0.3,
                       "sad": 0.2, "angry": 0.8, "fear": 0.8, "disgust": 0.5}

        dominant = max(emotions, key=emotions.get)
        confidence = emotions[dominant]
        valence = valence_map.get(dominant, 0.0) * confidence
        arousal = arousal_map.get(dominant, 0.3) * confidence

        self.history.append({"timestamp": timestamp, "dominant": dominant,
                             "confidence": confidence, "valence": valence, "arousal": arousal})
        cutoff = timestamp - self.window
        self.history = [h for h in self.history if h["timestamp"] >= cutoff]

        current_arousal = arousal
        trend = "stable"
        if len(self.history) >= 10:
            past_arousal = np.mean([h["arousal"] for h in self.history[:-5]])
            trend = "rising" if current_arousal > past_arousal else \
                    ("falling" if current_arousal < past_arousal else "stable")

        volatility = float(np.std([h["arousal"] for h in self.history[-5:]])) if len(self.history) >= 5 else 0.0

        return {"current_valence": valence, "current_arousal": current_arousal,
                "dominant_emotion": dominant, "trend": trend, "volatility": volatility}
```

**3.4.3 Chat Duygu Korelasyonu**

```python
class ChatCorrelationEngine:
    """Chat mesajlarini analiz ederek video icerigiyle korelasyon kurar."""

    def __init__(self, window: float = 5.0):
        self.window = window
        self.message_buffer: List[Dict] = []

    def process_messages(self, messages: List[Dict]) -> Dict:
        if not messages:
            return {"volume": 0.0, "sentiment": 0.0, "intensity": 0.0, "is_exciting": False}

        times = [m.get("timestamp", 0) for m in messages]
        duration = max(times) - min(times) if len(times) >= 2 else 0.1
        volume = len(messages) / max(duration, 0.1)

        texts = [m.get("text", "") for m in messages if m.get("text")]
        if texts:
            from services.chat_sentiment import chat_sentiment
            sentiment = chat_sentiment.analyze_batch(texts)
            avg_sentiment = sentiment.get("avg_score", 0.0)
        else:
            avg_sentiment = 0.0

        hype_keywords = {"pog", "poggers", "W", "lol", "lmao", "holy",
                         "insane", "clutch", "gg", "letsgo", "lets go"}
        all_words = set(" ".join(texts).lower().split())
        found_keywords = list(all_words & hype_keywords)
        intensity = min(1.0, volume / 20.0)

        return {"volume": volume, "sentiment": avg_sentiment, "intensity": intensity,
                "keywords": found_keywords,
                "is_exciting": intensity > 0.5 or len(found_keywords) >= 2}
```
**3.4.4 Highlight Tespit Algoritmasi**

```python
class HighlightDetector:
    """Zaman serisi uzerinde highlight anlarini tespit eder."""

    def __init__(self, config: ContentAnalysisConfig):
        self.config = config

    def detect(self, scores: List[ExcitementScore]) -> List[HighlightWindow]:
        if not scores:
            return []

        times = np.array([s.time for s in scores])
        values = np.array([s.score for s in scores])

        # 1. Gaussian smoothing
        from scipy.ndimage import gaussian_filter1d
        smoothed = gaussian_filter1d(values, sigma=1.0)

        # 2. Local maxima detection
        from scipy.signal import find_peaks
        peaks, properties = find_peaks(smoothed, height=self.config.highlight_threshold,
                                        distance=int(self.config.cooldown / self.config.hop_size),
                                        prominence=0.1)

        highlights = []
        for peak_idx in peaks:
            peak_time = times[peak_idx]
            peak_value = values[peak_idx]

            left, right = peak_idx, peak_idx
            half_max = peak_value / 2
            while left > 0 and smoothed[left] > half_max:
                left -= 1
            while right < len(smoothed) - 1 and smoothed[right] > half_max:
                right += 1

            start, end = times[left], times[right]
            duration = end - start
            if duration < self.config.min_highlight_duration or duration > self.config.max_highlight_duration:
                continue

            triggers = list(set(t for ws in scores[left:right+1] for t in ws.triggered_by))
            highlights.append(HighlightWindow(start=start, end=end, peak_score=float(peak_value),
                                               avg_score=float(np.mean(smoothed[left:right+1])),
                                               duration=duration, triggers=triggers))

        # 3. Cakisanlari birlestir
        return self._merge_overlapping(highlights)

    def _merge_overlapping(self, highlights: List[HighlightWindow]) -> List[HighlightWindow]:
        if not highlights:
            return []
        sorted_h = sorted(highlights, key=lambda h: h.start)
        merged = [sorted_h[0]]
        for h in sorted_h[1:]:
            last = merged[-1]
            if h.start <= last.end:
                merged[-1] = HighlightWindow(start=last.start, end=max(last.end, h.end),
                                              peak_score=max(last.peak_score, h.peak_score),
                                              avg_score=(last.avg_score + h.avg_score) / 2,
                                              duration=max(last.end, h.end) - last.start,
                                              triggers=list(set(last.triggers + h.triggers)))
            else:
                merged.append(h)
        return merged
```

### 3.5 API Sozlesmesi

```python
class ContentAnalysisService:
    """Icerik analizi servisi - tum sinyalleri birlestiren ust API."""

    async def analyze_stream_segment(self, video_path: str,
                                       chat_log_path: Optional[str] = None,
                                       audio_path: Optional[str] = None) -> Dict:
        """
        Returns: {
            "excitement_profile": [ExcitementScore], "highlights": [HighlightWindow],
            "emotion_arc": EmotionArc, "best_moments": [(start,end,score)],
            "summary": {"peak_score": 0.92, "avg_score": 0.45, "total_highlights": 5, ...}
        }
        """
        ...

    async def analyze_live_frame(self, frame: np.ndarray, timestamp: float) -> AnalysisFrame: ...
    def get_highlight_edl(self, highlights: List[HighlightWindow]) -> List[Tuple]: ...
```

### 3.6 Render Pipeline Entegresyonu

```ascii
[ContentAnalysisService.analyze_stream_segment()]
    |
    v
[ClipSpec'e yansitma]:
    - composite_score = peak highlight score
    - category = dominant emotion-based kategori
    - emotion_arc.enabled = True
    - emotion_arc.segments = EmotionArcSegment[]
    - beat_sync.enabled = True (audio energy varsa)
    - time_range = highlight.start - highlight.end
    - confidence = highlight peak confidence
```

### 3.7 Performans Dar Bogazlari ve Cozumleri

| Dar Bogaz | Belirti | Cozum |
|-----------|---------|-------|
| Tum sinyalleri es zamanli isleme | Yuksek CPU/GPU | Async pipeline, her sinyal ayri coroutine |
| Chat analizi (1000+ msg/s) | API gecikmesi | Batch processing, ornekleme |
| Ses spektral analizi | Agir hesaplama | Sadece highlight pencerelerinde |
| Cozunurluk analizi (4K) | Frame decode yavas | Her N karede, dusuk cozunurlukte |

---
## 4. AI-Powered Edit Decision Engine (AI Tabanli Duzenleme Karar Motoru)

### 4.1 Amac

Analiz katmanindan gelen tum verileri kullanarak otomatik duzenleme kararlari uretir: kesim noktasi, klip suresi, muzik senkronizasyonu, efekt atamasi, EDL olusturma.

### 4.2 Mimari

```ascii
[Analiz Verileri (Face, Scene, Content, Audio, Chat)]
    |
    v
[Edit Feature Extractor] -- feature vector -->
    |
    v
[Decision Engine: Rule-based + ML hybrid]
    |
    v
[EditCandidate Generator] --> [EDL Generator] --> [ClipSpec]
```

### 4.3 Veri Yapilari (Python)

```python
class EditRule(BaseModel):
    """Duzenleme kurali."""
    name: str
    condition: str                   # Python eval expression
    action: str                      # "create_candidate", "add_effect", etc.
    priority: int = 0
    params: Dict = Field(default_factory=dict)

    def evaluate(self, context: Dict) -> Optional[Dict]:
        try:
            if eval(self.condition, {"__builtins__": {}}, context):
                return {"action": self.action, "params": self.params}
        except Exception:
            return None
        return None


class EditCandidate(BaseModel):
    """Duzenleme adayi."""
    source_path: str
    time_range: Tuple[float, float]
    score: float = Field(ge=0.0, le=1.0)
    category: str = "general"
    suggested_effects: List[str] = Field(default_factory=list)
    suggested_speed: float = 1.0
    suggested_transition: Optional[str] = None
    emotion: Optional[str] = None
    motion_level: Optional[str] = None
    audio_level: Optional[str] = None
    chat_volume: float = 0.0
    is_final: bool = False


class EditDecision(BaseModel):
    """Nihai duzenleme karari."""
    candidates: List[EditCandidate] = Field(default_factory=list)
    total_duration: float = 0.0
    pacing: str = "normal"
    style: str = "highlight"
    music_path: Optional[str] = None
    clip_spec_overrides: Dict = Field(default_factory=dict)


class EditDecisionConfig(BaseModel):
    """Duzenleme karar motoru yapilandirmasi."""
    max_clip_duration: float = 60.0
    min_clip_duration: float = 5.0
    target_duration: float = 30.0
    clip_count_range: Tuple[int, int] = (1, 5)
    rules_path: Optional[str] = "config/edit_rules.json"
    enable_ml_decision: bool = False
    ml_model_path: Optional[str] = None
    enable_beat_sync: bool = True
    beat_sync_weight: float = 0.3
    pacing_presets: Dict[str, Dict] = Field(default_factory=lambda: {
        "fast": {"max_scene_duration": 3.0, "transition_duration": 0.3, "speed_boost": 1.2},
        "normal": {"max_scene_duration": 6.0, "transition_duration": 0.5, "speed_boost": 1.0},
        "slow": {"max_scene_duration": 12.0, "transition_duration": 0.8, "speed_boost": 0.8},
    })
```
### 4.4 Algoritmalar

**4.4.1 Kural Tabanli Karar Motoru**

```python
class RuleBasedDecisionEngine:
    """Kural tabani kullanarak duzenleme kararlari uretir."""

    def __init__(self, config: EditDecisionConfig):
        self.config = config
        self.rules: List[EditRule] = self._load_rules()

    def _load_rules(self) -> List[EditRule]:
        rules_path = self.config.rules_path
        if rules_path and Path(rules_path).exists():
            with open(rules_path) as f:
                return [EditRule(**r) for r in json.load(f).get("rules", [])]
        return self._default_rules()

    def _default_rules(self) -> List[EditRule]:
        return [
            EditRule(name="highlight_moment", priority=10,
                     condition="composite_score > 0.7", action="create_candidate",
                     params={"score_bonus": 0.2}),
            EditRule(name="face_zoom", priority=5,
                     condition="emotion in ('happy', 'surprise') and face_presence > 0.8",
                     action="add_effect", params={"effect": "zoom_in", "intensity": 0.3}),
            EditRule(name="action_segment", priority=8,
                     condition="motion_level == 'high' and audio_spike",
                     action="set_pacing", params={"pacing": "fast", "speed": 1.3}),
            EditRule(name="calm_segment", priority=3,
                     condition="emotion == 'sad' and motion_level == 'low'",
                     action="set_pacing", params={"pacing": "slow", "speed": 0.8}),
            EditRule(name="chat_moment", priority=7,
                     condition="chat_volume > 30 and composite_score > 0.5",
                     action="create_candidate", params={"score_bonus": 0.15}),
            EditRule(name="scene_transition", priority=9,
                     condition="scene_change > 0.3", action="mark_cut_point", params={}),
            EditRule(name="beat_aligned_cut", priority=6,
                     condition="beat_strength > 0.7", action="prefer_cut_point",
                     params={"tolerance": 0.1}),
        ]

    def evaluate(self, context: Dict) -> List[Dict]:
        decisions = []
        for rule in sorted(self.rules, key=lambda r: -r.priority):
            result = rule.evaluate(context)
            if result:
                decisions.append(result)
        return decisions
```

**4.4.2 Optimal Klip Suresi Belirleme**

```python
class ClipDurationOptimizer:
    """Analiz sinyallerine gore en uygun klip suresini belirler."""

    BASE_DURATIONS = {"tiktok": (15, 60), "instagram": (15, 90),
                      "youtube_shorts": (15, 60), "kick": (15, 120), "twitter": (10, 140)}

    def __init__(self, config: EditDecisionConfig):
        self.config = config

    def optimal_duration(self, excitement_profile: List[ExcitementScore],
                          beat_grid: Optional[BeatGrid] = None,
                          platform: str = "tiktok") -> float:
        if not excitement_profile:
            return self.config.target_duration

        scores = np.array([s.score for s in excitement_profile])
        times = np.array([s.time for s in excitement_profile])

        weights = scores - np.min(scores)
        weighted_time = np.average(times, weights=weights) if np.sum(weights) > 0 else times[len(times)//2]

        half_window = self.config.target_duration / 2
        start, end = max(0, weighted_time - half_window), min(times[-1], weighted_time + half_window)

        # Beat alignment
        if beat_grid and beat_grid.beats:
            start = min(beat_grid.beats, key=lambda b: abs(b.time - start)).time
            end = min(beat_grid.beats, key=lambda b: abs(b.time - end)).time

        duration = end - start
        min_dur, max_dur = self.BASE_DURATIONS.get(platform, (15, 60))
        return max(self.config.min_clip_duration, min(self.config.max_clip_duration,
                                                       max(min_dur, min(max_dur, duration))))
```

**4.4.3 Muzik-Senkronize Edit Noktalari**

```python
class MusicSyncEditor:
    """Muzik ritmine gore edit noktalari belirler."""

    def __init__(self, beat_sync_weight: float = 0.3):
        self.beat_sync_weight = beat_sync_weight

    def align_cuts_to_beats(self, cut_points: List[float], beat_times: List[float],
                             tolerance: float = 0.1) -> List[float]:
        if not beat_times:
            return cut_points
        aligned = []
        for cut in cut_points:
            closest = min(beat_times, key=lambda b: abs(b - cut))
            aligned.append(closest if abs(closest - cut) <= tolerance else cut)
        return aligned

    def suggest_effect_on_beat(self, beat_times: List[float],
                                beat_strengths: List[float]) -> List[Dict]:
        suggestions = []
        for i, (time, strength) in enumerate(zip(beat_times, beat_strengths)):
            is_downbeat = (i % 4 == 0)
            if is_downbeat and strength > 0.7:
                suggestions.append({"time": time, "effect": "zoom_in",
                                    "intensity": 0.3, "duration": 0.2})
            elif strength > 0.5:
                suggestions.append({"time": time, "effect": "shake",
                                    "intensity": 0.1, "duration": 0.15})
        return suggestions
```
**4.4.4 Pacing Analizi (Edit Ritmi)**

```python
class PacingAnalyzer:
    """Duzenleme ritmini analiz eder ve pacing onerisi uretir."""

    def analyze(self, scenes: List[SceneScore],
                excitement_profile: List[ExcitementScore]) -> str:
        if not scenes:
            return "normal"

        avg_scene_dur = np.mean([s.duration for s in scenes])
        if not excitement_profile:
            return "normal" if avg_scene_dur > 4 else "fast"

        scores = [s.score for s in excitement_profile]
        volatility = float(np.std(scores)) if scores else 0.0

        if avg_scene_dur < 2.5 and volatility > 0.3:
            return "fast"
        elif avg_scene_dur > 6.0 or volatility < 0.15:
            return "slow"
        return "normal"
```

**4.4.5 Edit Decision List (EDL) Uretimi**

```python
class EDLGenerator:
    """Analiz sonuclarindan tam EDL uretir."""

    def __init__(self, config: EditDecisionConfig):
        self.config = config

    def generate_edl(self, candidates: List[EditCandidate], pacing: str,
                      beat_aligned: bool = True) -> List[Dict]:
        if not candidates:
            return []

        sorted_candidates = sorted(candidates, key=lambda c: -c.score)
        selected, total = [], 0.0
        max_dur = self.config.target_duration

        for c in sorted_candidates:
            dur = c.time_range[1] - c.time_range[0]
            if total + dur <= max_dur:
                selected.append(c)
                total += dur
            elif total < max_dur * 0.7:
                remaining = max_dur - total
                if remaining > self.config.min_clip_duration:
                    c.time_range = (c.time_range[0], c.time_range[0] + min(remaining, dur))
                    selected.append(c)
                    total += remaining

        selected.sort(key=lambda c: c.time_range[0])
        pacing_config = self.config.pacing_presets.get(pacing, self.config.pacing_presets["normal"])

        edl = []
        for i, c in enumerate(selected):
            entry = {"source": c.source_path, "start": c.time_range[0], "end": c.time_range[1],
                     "speed": c.suggested_speed * pacing_config.get("speed_boost", 1.0),
                     "effects": c.suggested_effects,
                     "transition": c.suggested_transition or "fade",
                     "transition_duration": pacing_config.get("transition_duration", 0.5),
                     "category": c.category}
            if c.emotion:
                entry["emotion"] = c.emotion
            if c.audio_level:
                entry["audio_level"] = c.audio_level
            edl.append(entry)
        return edl
```

### 4.5 API Sozlesmesi

```python
class EditDecisionService:
    """Duzenleme karar motoru."""

    async def generate_edit(self, analysis_result: Dict, platform: str = "tiktok",
                             style: str = "highlight") -> EditDecision:
        """Rule-based + ML kararlari, clip sure optimizasyonu, beat alignment,
           pacing belirleme, EDL olusturma, ClipSpec'e cevirme."""
        ...

    async def generate_clip_spec(self, decision: EditDecision) -> ClipSpec: ...
    def get_rules(self) -> List[Dict]: ...
    def update_rule(self, rule_name: str, updates: Dict) -> bool: ...
    def set_pacing(self, pacing: str): ...
```

### 4.6 Render Pipeline Entegresyonu

```ascii
[EditDecisionService.generate_edit()]
    |
    v
[ClipSpec'e yansitma]:
    - time_range = EDL'deki her entry
    - speed_segments = speed degerleri
    - effects = visual effects listesi
    - transitions = transition + duration
    - beat_sync = beat alignment
    - color_grading = emotion-based preset
```

EDL -> FFmpeg concat/xfade graph:
```bash
[clip1] --xfade--> [clip2] --xfade--> [clip3] ...
```

### 4.7 Performans Dar Bogazlari ve Cozumleri

| Dar Bogaz | Belirti | Cozum |
|-----------|---------|-------|
| Kural sayisi fazla (~50+) | Degerlendirme yavas | Kural indeksleme, oncelik gruplari |
| ML model inference (~5ms) | Karar gecikmesi | Async, sadece yuksek skorlu adaylarda |
| EDL optimizasyonu (NP-hard) | Kombinasyon patlamasi | Greedy selection, cooldown constraint |
| Coklu platform hedefi | Tekrar hesaplama | Platform profillerini cachele |

---
## 5. Quality Analysis (Kalite Analizi)

### 5.1 Amac

Render edilmis videonun kalitesini dogrulamak, gorsel/issel bozulmalari tespit etmek, platform gereksinimlerine uygunlugu kontrol etmek.

### 5.2 Mimari

```ascii
[Render Output] --> [Video Quality Metrics (VMAF, SSIM, PSNR)]
                --> [Audio Quality Metrics (LUFS, True Peak)]
                --> [Encoding Artifact Detection]
                --> [Compositing Validation]
                --> [Platform Compliance Check]
                       |
                       v
              [QualityReport + ComplianceCheck]
```

### 5.3 Veri Yapilari (Python)

```python
class QualityMetric(BaseModel):
    """Tek bir kalite metrigi."""
    name: str
    value: float
    score: float = Field(ge=0.0, le=1.0)
    threshold: Optional[float] = None
    passed: bool = True
    details: Dict = Field(default_factory=dict)


class ComplianceCheck(BaseModel):
    """Platform uyumluluk kontrolu."""
    platform: str
    max_bitrate: int = 0
    max_resolution: Tuple[int, int] = (0, 0)
    required_codecs: List[str] = Field(default_factory=list)
    max_duration: float = 0.0
    aspect_ratio: Optional[str] = None
    max_file_size: int = 0
    audio_codec: str = "aac"
    audio_bitrate: int = 0


class QualityReport(BaseModel):
    """Kalite raporu."""
    video_path: str
    passed: bool = False
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    video_metrics: List[QualityMetric] = Field(default_factory=list)
    vmaf_score: Optional[float] = None
    ssim_score: Optional[float] = None
    psnr_score: Optional[float] = None
    audio_metrics: List[QualityMetric] = Field(default_factory=list)
    lufs_score: Optional[float] = None
    true_peak: Optional[float] = None
    artifacts: List[str] = Field(default_factory=list)
    artifact_severity: str = "none"
    compliance: List[ComplianceCheck] = Field(default_factory=list)
    compliance_score: float = 1.0
    ffprobe_info: Dict = Field(default_factory=dict)
    duration: float = 0.0
    resolution: Tuple[int, int] = (0, 0)
    bitrate: int = 0
    fps: float = 0.0


class QualityAnalysisConfig(BaseModel):
    """Kalite analizi yapilandirmasi."""
    vmaf_model_path: Optional[str] = "models/vmaf_v0.6.1.json"
    ssim_enabled: bool = True
    psnr_enabled: bool = True
    lufs_enabled: bool = True
    vmaf_threshold: float = 80.0
    ssim_threshold: float = 0.85
    psnr_threshold: float = 30.0
    lufs_threshold: Tuple[float, float] = (-23.0, -9.0)
    true_peak_threshold: float = -1.0
    detect_banding: bool = True
    detect_blocking: bool = True
    detect_ringing: bool = True
    detect_noise: bool = True
    detect_black_frames: bool = True
    detect_frozen_frames: bool = True
    check_platform_compliance: bool = True
    default_platforms: List[str] = Field(default_factory=lambda: ["tiktok", "youtube"])
```
### 5.4 Algoritmalar

**5.4.1 VMAF (Video Multimethod Assessment Fusion)**

```python
class VMAFCalculator:
    """Netflix VMAF: referans goruntuye gore video kalitesi (0-100)."""

    def __init__(self, model_path: str):
        self.model_path = model_path

    async def compute(self, distorted: str, reference: str) -> float:
        """FFmpeg libvmaf filter ile VMAF hesapla."""
        cmd = [
            "ffmpeg", "-y",
            "-i", distorted,
            "-i", reference,
            "-filter_complex",
            f"[0:v][1:v]libvmaf=model_path={self.model_path}",
            "-f", "null", "-"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        output = stderr.decode()

        # "VMAF score: 85.437" parse
        for line in output.split("\n"):
            if "VMAF score:" in line:
                return float(line.split(":")[1].strip())
        return 0.0


class SSIMCalculator:
    """SSIM: Yapisal benzerlik (0-1)."""

    async def compute(self, distorted: str, reference: str) -> float:
        cmd = ["ffmpeg", "-y", "-i", distorted, "-i", reference,
               "-filter_complex", "[0:v][1:v]ssim",
               "-f", "null", "-"]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        for line in stderr.decode().split("\n"):
            if "SSIM" in line and "All:" in line:
                try:
                    return float(line.split("All:")[1].split()[0])
                except (IndexError, ValueError):
                    pass
        return 0.0


class PSNRCalculator:
    """PSNR: Zirve Sinyal-Gurultu Orani (dB)."""

    async def compute(self, distorted: str, reference: str) -> float:
        cmd = ["ffmpeg", "-y", "-i", distorted, "-i", reference,
               "-filter_complex", "[0:v][1:v]psnr",
               "-f", "null", "-"]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        for line in stderr.decode().split("\n"):
            if "PSNR" in line and "average:" in line:
                try:
                    return float(line.split("average:")[1].split()[0])
                except (IndexError, ValueError):
                    pass
        return 0.0
```

**5.4.2 Ses Kalite Metrikleri (LUFS, True Peak)**

```python
class AudioQualityAnalyzer:
    """EBU R128 standardina gore ses kalite olcumu."""

    async def measure_loudness(self, audio_path: str) -> Dict:
        """
        LUFS (Loudness Units relative to Full Scale) olcumu.

        FFmpeg loudnorm filter ile:
        - Integrated LUFS
        - Short-term LUFS
        - True Peak (dBTP)
        - Loudness Range (LRA)
        """
        cmd = [
            "ffmpeg", "-i", audio_path,
            "-af", "loudnorm=I=-16:dual_mono=true:print_format=json",
            "-f", "null", "-"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        output = stderr.decode()

        # JSON ciktisini parse et
        import re
        json_match = re.search(r"\{.*\}", output, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return {
                    "input_i": float(data.get("input_i", 0)),      # Integrated LUFS
                    "input_tp": float(data.get("input_tp", 0)),    # True Peak dBTP
                    "input_lra": float(data.get("input_lra", 0)),  # Loudness Range
                    "input_thresh": float(data.get("input_thresh", 0)),
                }
            except (json.JSONDecodeError, ValueError):
                pass

        return {"input_i": 0.0, "input_tp": 0.0, "input_lra": 0.0, "input_thresh": 0.0}
```
**5.4.3 Kodlama Artifact Tespiti**

```python
class ArtifactDetector:
    """Gorsel bozulma tespiti (banding, blocking, ringing, noise)."""

    async def detect_all(self, video_path: str, sample_interval: float = 5.0) -> Dict:
        """Video boyunca ornek karelerde artifact ara."""
        results = {"banding": 0.0, "blocking": 0.0, "ringing": 0.0, "noise": 0.0,
                   "severity": "none"}

        # Her N saniyede bir kare al
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = ["ffmpeg", "-i", video_path,
                   f"-vf", f"fps=1/{sample_interval}",
                   f"{tmpdir}/frame_%04d.png"]
            subprocess.run(cmd, capture_output=True, timeout=60)

            # Her kareyi analiz et
            frames = sorted(Path(tmpdir).glob("frame_*.png"))
            for frame_path in frames:
                frame = cv2.imread(str(frame_path))
                if frame is None:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                # Banding: histogram bosluk tespiti
                hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
                zero_bins = np.sum(hist == 0)
                banding_score = min(1.0, zero_bins / 100.0)

                # Blocking: DCT frekans analizi (blok sinirlarinda enerji)
                h, w = gray.shape
                block_energy = 0.0
                for y in range(0, h - 8, 8):
                    for x in range(0, w - 8, 8):
                        block = gray[y:y+8, x:x+8].astype(np.float32)
                        dct = cv2.dct(block)
                        ac_energy = np.sum(dct[1:, 1:] ** 2)
                        block_energy += ac_energy / (dct[0, 0] ** 2 + 1e-6)
                blocking_score = min(1.0, block_energy / ((h//8) * (w//8)) * 10)

                # Noise: Laplacian variance + median filter farki
                lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
                noise_score = max(0.0, 1.0 - lap_var / 500.0)

                results["banding"] = max(results["banding"], float(banding_score))
                results["blocking"] = max(results["blocking"], float(blocking_score))
                results["noise"] = max(results["noise"], float(noise_score))

        max_severity = max(results.values()) if results.values() else 0.0
        results["severity"] = ("high" if max_severity > 0.6 else
                               "medium" if max_severity > 0.3 else "low" if max_severity > 0.1 else "none")
        return results
```

**5.4.4 Platform Uyumluluk Kontrolu**

```python
class PlatformComplianceChecker:
    """Her platformun gereksinimlerine gore uyumluluk kontrolu."""

    PLATFORM_SPECS = {
        "tiktok": {"max_bitrate": 8_000_000, "max_resolution": (1080, 1920),
                    "required_codecs": ["h264"], "max_duration": 60.0,
                    "aspect_ratio": "9:16", "max_file_size": 500_000_000,
                    "audio_codec": "aac", "audio_bitrate": 192_000},
        "youtube_shorts": {"max_bitrate": 50_000_000, "max_resolution": (1080, 1920),
                            "required_codecs": ["h264", "hevc", "av1"],
                            "max_duration": 60.0, "aspect_ratio": "9:16",
                            "max_file_size": 2_000_000_000,
                            "audio_codec": "aac", "audio_bitrate": 384_000},
        "instagram": {"max_bitrate": 5_000_000, "max_resolution": (1080, 1920),
                       "required_codecs": ["h264"], "max_duration": 90.0,
                       "aspect_ratio": "9:16", "max_file_size": 100_000_000,
                       "audio_codec": "aac", "audio_bitrate": 128_000},
        "kick": {"max_bitrate": 8_000_000, "max_resolution": (1080, 1920),
                  "required_codecs": ["h264"], "max_duration": 120.0,
                  "max_file_size": 1_000_000_000,
                  "audio_codec": "aac", "audio_bitrate": 192_000},
        "twitter": {"max_bitrate": 25_000_000, "max_resolution": (1920, 1080),
                     "required_codecs": ["h264"], "max_duration": 140.0,
                     "aspect_ratio": "16:9", "max_file_size": 512_000_000,
                     "audio_codec": "aac", "audio_bitrate": 128_000},
    }

    def __init__(self, config: QualityAnalysisConfig):
        self.config = config

    async def check(self, video_path: str, platforms: List[str] = None) -> List[ComplianceCheck]:
        if platforms is None:
            platforms = self.config.default_platforms

        # ffprobe ile video bilgisi al
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_format", "-show_streams", video_path]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        info = json.loads(stdout.decode())

        streams = info.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
        fmt = info.get("format", {})

        actual = {
            "bitrate": int(fmt.get("bit_rate", 0)),
            "width": int(video_stream.get("width", 0)),
            "height": int(video_stream.get("height", 0)),
            "codec": video_stream.get("codec_name", ""),
            "duration": float(fmt.get("duration", 0)),
            "file_size": int(fmt.get("size", 0)),
            "audio_codec": audio_stream.get("codec_name", ""),
            "audio_bitrate": int(audio_stream.get("bit_rate", 0)),
        }

        results = []
        for platform in platforms:
            spec = self.PLATFORM_SPECS.get(platform)
            if not spec:
                continue

            issues = []
            if spec.get("max_bitrate") and actual["bitrate"] > spec["max_bitrate"]:
                issues.append("bitrate")
            if spec.get("max_file_size") and actual["file_size"] > spec["max_file_size"]:
                issues.append("file_size")
            if spec.get("max_resolution") and (actual["width"] > spec["max_resolution"][0] or
                                                actual["height"] > spec["max_resolution"][1]):
                issues.append("resolution")
            if spec.get("required_codecs") and actual["codec"] not in spec["required_codecs"]:
                issues.append("codec")
            if spec.get("max_duration") and actual["duration"] > spec["max_duration"]:
                issues.append("duration")
            if spec.get("audio_codec") and actual["audio_codec"] != spec["audio_codec"]:
                issues.append("audio_codec")

            results.append(ComplianceCheck(
                platform=platform,
                max_bitrate=spec.get("max_bitrate", 0),
                max_resolution=spec.get("max_resolution", (0, 0)),
                required_codecs=spec.get("required_codecs", []),
                max_duration=spec.get("max_duration", 0),
                aspect_ratio=spec.get("aspect_ratio"),
                max_file_size=spec.get("max_file_size", 0),
                audio_codec=spec.get("audio_codec", "aac"),
                audio_bitrate=spec.get("audio_bitrate", 0),
            ))

        return results
```
### 5.5 API Sozlesmesi

```python
class QualityAnalysisService:
    """Kalite analizi servisi."""

    async def analyze(self, video_path: str, reference_path: Optional[str] = None,
                       config: Optional[QualityAnalysisConfig] = None) -> QualityReport:
        """
        1. ffprobe ile metadata topla
        2. VMAF/SSIM/PSNR hesapla (reference varsa)
        3. LUFS/True Peak olc
        4. Artifact tespiti
        5. Platform compliance check
        6. Rapor oluşutur
        """
        ...

    async def check_compliance(self, video_path: str,
                                platforms: List[str] = None) -> List[ComplianceCheck]: ...

    async def get_optimization_suggestions(self, video_path: str,
                                            target_platform: str) -> Dict: ...
```

### 5.6 Render Pipeline Entegresyonu

```ascii
[RenderPipeline.render()] - [video ciktisi]
    |
    v
[QualityAnalysisService.analyze()]
    |
    v
[QC Report] --> Basarili: devam
            --> Basarisiz: yeniden render (CRF ayari, codec değişikliği, vs.)
            
[Platform Compliance] --> TikTok: max 60s, 9:16, h264, <=8Mbps
                     --> YouTube: max 60s, 9:16, h264/hevc/av1
                     --> Instagram: max 90s, 9:16, h264, <=5Mbps
```

FFmpeg normalizasyon (LUFS hedefleme):
```bash
ffmpeg -i input.mp4 -af "loudnorm=I=-14:LRA=1:TP=-1" -c:v copy output.mp4
```

### 5.7 Performans Dar Bogazlari ve Cozumleri

| Dar Bogaz | Belirti | Cozum |
|-----------|---------|-------|
| VMAF full reference (tum kareler) | Cok yavas | Her N karede ornekleme |
| Artifact tespiti (her kare) | GPU/CPU yuksek | Her 5-10 saniyede bir kare |
| FFmpeg loudnorm parse | JSON parse yavas | Regex ile hizli parse |
| Platform compliance | Statik veri | Cache'le, once hesapla |

### 5.8 Benchmark Hedefleri

| Metrik | Hedef | Test Kosulu |
|--------|-------|-------------|
| VMAF | >80/100 | 1080p, 8Mbps, x264 fast |
| SSIM | >0.90 | Referans goruntu ile |
| PSNR | >35dB | Referans goruntu ile |
| LUFS | -14 +/- 2 | EBU R128 standard |
| True Peak | <-1dBTP | Loudness normalized |
| Artifact severity | <"low" | Tum video boyunca |
| Analiz suresi | <10% render suresi | async pipeline |

---

## Ek A: Modul Etkilesim Tablosu

| Modul | Okudugu Veri | Urettigi Veri | Tuketen Modul |
|-------|-------------|--------------|---------------|
| Face Tracking | Frame, ONNX model | FaceTrack, FaceCluster, emotion | Crop, AutoEditor, Thumbnail |
| Scene Detection | Frame pairs | SceneBoundary, SceneScore | EditDecision, Speed, Transition |
| Content Analysis | Face + Motion + Audio + Chat | ExcitementScore, HighlightWindow | EditDecision, BeatSync, Highlight |
| Edit Decision | Tum analiz ciktilari | EditDecision, EDL, ClipSpec | RenderPipeline |
| Quality Analysis | Render ciktisi | QualityReport, ComplianceCheck | DevOps, Upload pipeline |

## Ek B: Mevcut Kod ile Entegrasyon

Mevcut servislerle uyum:

- `services/analysis/face_emotion.py` -> FaceTrackingService'in emotion bileseni
- `services/analysis/motion_detection.py` -> Motion sinyali (Content Analysis)
- `services/analysis/audio_analysis.py` -> Audio sinyali (Content Analysis)
- `services/analysis/pipeline.py` -> EventDetector -> MultiSignalFusionEngine
- `services/scene_detection.py` -> SceneDetectionService tabani
- `services/auto_editor.py` -> EditDecisionService'in ClipSpec uretimi
- `services/beat_sync.py` -> MusicSyncEditor beat alignment
- `services/quality_control.py` -> QualityAnalysisService tabani
- `services/emotion_arc.py` -> EmotionArcTracker'in FFmpeg filter uretimi
- `services/chat_sentiment.py` -> Chat sinyali (Content Analysis)
- `services/edit_spec.py` -> ClipSpec modeli (butun modullerin ciktisi)
- `services/render_pipeline.py` -> Tum analiz kararlarini FFmpeg graph'a cevirir

## Ek C: ONNX Model Dizini

```
models/
  face_detection.onnx          # UltraFace / YOLOv5-face (640x640)
  face_landmark.onnx           # 68-point landmark (MobileNet)
  face_recognition.onnx        # ArcFace 128d embedding
  emotion_classification.onnx  # 7-emotion classifier (MobileNet)
  scene_classification.onnx    # 8-class scene transition
  edit_decision.onnx           # Edit parametre tahmini (opsiyonel)
  vmaf_v0.6.1.json             # VMAF model (Netflix)
```
