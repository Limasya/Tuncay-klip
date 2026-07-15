"""
Pipeline API router — microservice-based endpoints.
Controls the event-driven pipeline orchestrator.
All microservice imports are lazy to avoid startup failures
when Redis or ML dependencies are unavailable.
"""
import asyncio
import json
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger("pipeline_api")

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

_ws_clients: list = []


def _get_orch():
    """Lazy import of microservices orchestrator."""
    try:
        from microservices.orchestrator import orchestrator
        return orchestrator
    except Exception as e:
        logger.warning("Microservices orchestrator unavailable: %s", e)
        return None


class StartStreamRequest(BaseModel):
    stream_url: str
    target_fps: int = 2
    buffer_seconds: int = 30


class ChatMessageRequest(BaseModel):
    text: str
    user: str = ""


@router.post("/start")
async def start_pipeline(request: StartStreamRequest):
    """Start the event-driven pipeline with a stream URL."""
    orchestrator = _get_orch()
    if orchestrator is None:
        raise HTTPException(503, "Microservices orchestrator unavailable (Redis required)")
    if orchestrator._is_running:
        raise HTTPException(400, "Pipeline already running")

    asyncio.create_task(orchestrator.start_stream(
        stream_url=request.stream_url,
        target_fps=request.target_fps,
        buffer_seconds=request.buffer_seconds,
    ))

    return {"message": "Pipeline starting...", "url": request.stream_url}


@router.post("/stop")
async def stop_pipeline():
    """Stop the pipeline gracefully."""
    orchestrator = _get_orch()
    if orchestrator is None:
        raise HTTPException(503, "Microservices orchestrator unavailable")
    if not orchestrator._is_running:
        raise HTTPException(400, "Pipeline not running")
    await orchestrator.stop()
    return {"message": "Pipeline stopped"}


@router.get("/status")
async def pipeline_status():
    """Get full pipeline status with all service metrics."""
    orchestrator = _get_orch()
    if orchestrator is None:
        return {"error": "Microservices orchestrator unavailable (Redis required)"}
    return orchestrator.get_full_status()


@router.post("/chat")
async def inject_chat(request: ChatMessageRequest):
    """Inject a chat message for analysis (testing)."""
    orchestrator = _get_orch()
    if orchestrator is None:
        raise HTTPException(503, "Microservices orchestrator unavailable")
    result = await orchestrator.inject_chat_message(request.text, request.user)
    if result:
        if hasattr(result, "model_dump"):
            return result.model_dump()
        return result
    raise HTTPException(500, "Chat analysis not available")


@router.post("/analyze-frame")
async def analyze_frame():
    """Analyze a test frame (for demo/testing)."""
    import numpy as np
    orchestrator = _get_orch()
    if orchestrator is None:
        raise HTTPException(503, "Microservices orchestrator unavailable")
    try:
        test_frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
        result = await orchestrator.analyze_single_frame(test_frame)
        return {
            "faces": len(result.faces),
            "emotions": len(result.emotions),
            "poses": len(result.poses),
            "inference_ms": result.inference_time_ms,
        }
    except Exception as e:
        raise HTTPException(503, f"Frame analysis failed: {type(e).__name__}: {e}")


@router.get("/events")
async def get_recent_events(last_n: int = 50):
    """Get recent events from the event bus."""
    orchestrator = _get_orch()
    if orchestrator and orchestrator.event_bus:
        events = orchestrator.event_bus.get_all_recent(last_n)
        return [e.model_dump(mode="json") if hasattr(e, "model_dump") else e for e in events]
    return []


@router.get("/events/{event_type}")
async def get_events_by_type(event_type: str, last_n: int = 20):
    """Get recent events of a specific type."""
    orchestrator = _get_orch()
    if orchestrator and orchestrator.event_bus:
        events = orchestrator.event_bus.get_history(event_type, last_n)
        return [e.model_dump(mode="json") if hasattr(e, "model_dump") else e for e in events]
    return []


@router.get("/score")
async def get_current_score():
    """Get the current highlight score."""
    orchestrator = _get_orch()
    if orchestrator is None:
        raise HTTPException(503, "Microservices orchestrator unavailable")
    if not orchestrator.event_bus:
        await orchestrator.initialize()
    if orchestrator.event_detector:
        score = orchestrator.event_detector.get_latest_score()
        return score.model_dump() if hasattr(score, "model_dump") else score
    raise HTTPException(500, "Event detector not available")


@router.get("/metrics")
async def get_metrics():
    """Get event bus metrics."""
    orchestrator = _get_orch()
    if orchestrator and orchestrator.event_bus:
        return orchestrator.event_bus.metrics
    return {}


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """WebSocket for real-time event streaming to the dashboard."""
    await websocket.accept()
    _ws_clients.append(websocket)
    logger.info("WebSocket client connected (%d total)", len(_ws_clients))

    orchestrator = _get_orch()
    try:
        if orchestrator:
            status = orchestrator.get_full_status()
            await websocket.send_json({"type": "status", "data": status})
    except Exception:
        pass

    async def _ws_event_handler(event):
        try:
            data = event.model_dump(mode="json") if hasattr(event, "model_dump") else event
            await websocket.send_json({"type": "event", "data": data})
        except Exception:
            pass

    if orchestrator and orchestrator.event_bus:
        orchestrator.event_bus.subscribe_wildcard("*", _ws_event_handler)

    try:
        while True:
            await asyncio.sleep(2)
            if orchestrator and orchestrator.event_detector:
                score = orchestrator.event_detector.get_latest_score()
                await websocket.send_json({
                    "type": "score",
                    "data": score.model_dump() if hasattr(score, "model_dump") else score,
                })
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)
        logger.info("WebSocket client disconnected (%d total)", len(_ws_clients))


@router.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    target_fps: int = 2,
    max_seconds: int = 60,
):
    """Upload a video file for offline pipeline analysis."""
    import cv2
    import numpy as np

    if not file.filename or not file.filename.lower().endswith(('.mp4', '.avi', '.mkv', '.mov', '.webm')):
        raise HTTPException(400, "Unsupported video format. Use mp4, avi, mkv, mov, or webm.")

    orchestrator = _get_orch()
    if orchestrator is None:
        raise HTTPException(503, "Microservices orchestrator unavailable")

    upload_dir = os.path.join("data", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"upload_{int(time.time())}_{file.filename}")

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    logger.info("Video uploaded: %s (%d bytes)", file_path, len(content))

    if not orchestrator.event_bus:
        await orchestrator.initialize()

    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        raise HTTPException(500, "Failed to open video file")

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / video_fps if video_fps > 0 else 0

    frame_skip = max(1, int(video_fps / target_fps))
    frames_to_process = min(
        int(max_seconds * target_fps),
        int(total_frames / frame_skip),
    )

    results = {
        "file": file.filename,
        "duration_seconds": round(duration, 1),
        "video_fps": round(video_fps, 1),
        "target_fps": target_fps,
        "frames_processed": 0,
        "faces_detected": 0,
        "emotions_detected": 0,
        "poses_detected": 0,
        "avg_inference_ms": 0,
        "events_generated": 0,
    }

    frame_idx = 0
    processed = 0
    total_inference = 0.0

    while cap.isOpened() and processed < frames_to_process:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_skip == 0:
            if frame.shape[0] > 720:
                h, w = frame.shape[:2]
                scale = 720 / h
                frame = cv2.resize(frame, (int(w * scale), 720))

            result = await orchestrator.analyze_single_frame(
                frame, f"upload_{frame_idx:06d}"
            )

            results["faces_detected"] += len(result.faces)
            results["emotions_detected"] += len(result.emotions)
            results["poses_detected"] += len(result.poses)
            total_inference += result.inference_time_ms
            processed += 1

        frame_idx += 1

    cap.release()

    results["frames_processed"] = processed
    results["avg_inference_ms"] = round(
        total_inference / processed if processed > 0 else 0, 1
    )

    if orchestrator.event_bus:
        events = orchestrator.event_bus.get_all_recent(500)
        results["events_generated"] = len([
            e for e in events
            if "upload" in str(e.payload)
            or e.source_service in ("video-analysis", "event-detector")
        ])

    if orchestrator.event_detector:
        score = orchestrator.event_detector.get_latest_score()
        results["final_score"] = score.model_dump() if hasattr(score, "model_dump") else score

    return results


async def save_pipeline_clip_to_db(clip_data: dict):
    """Save a pipeline-generated clip to the database."""
    try:
        from services.database import async_session
        from models.database import Clip, ClipStatus, ClipCategory, TriggerType

        async with async_session() as session:
            category_map = {
                "exciting": ClipCategory.EXCITING,
                "hype": ClipCategory.EXCITING,
                "celebration": ClipCategory.VICTORY,
                "emotional": ClipCategory.EMOTIONAL,
                "funny": ClipCategory.FUNNY,
                "highlight": ClipCategory.SKILL,
            }
            cat = clip_data.get("category", "other")
            db_category = category_map.get(cat, ClipCategory.OTHER)

            clip = Clip(
                broadcaster_id=1,
                title=f"Pipeline Clip - {cat.title()}",
                description=f"Auto-generated. Score: {clip_data.get('highlight_score', 0):.3f}",
                category=db_category,
                status=ClipStatus.READY,
                trigger_type=TriggerType.COMPOSITE,
                duration_seconds=clip_data.get("duration_seconds", 0),
                video_path=clip_data.get("file_path", ""),
                thumbnail_path=clip_data.get("thumbnail_path", ""),
                emotion_score=clip_data.get("highlight_score", 0),
            )
            session.add(clip)
            await session.commit()
            logger.info("Clip saved to DB: %s - %s", clip.id, cat)
    except Exception as e:
        logger.error("Failed to save clip to DB: %s", e)
