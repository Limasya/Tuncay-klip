"""
Pipeline API router — new microservice-based endpoints.
Controls the event-driven pipeline orchestrator.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from microservices.orchestrator import orchestrator

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


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
    if orchestrator._is_running:
        raise HTTPException(400, "Pipeline already running")

    import asyncio
    asyncio.create_task(orchestrator.start_stream(
        stream_url=request.stream_url,
        target_fps=request.target_fps,
        buffer_seconds=request.buffer_seconds,
    ))

    return {"message": "Pipeline starting...", "url": request.stream_url}


@router.post("/stop")
async def stop_pipeline():
    """Stop the pipeline gracefully."""
    if not orchestrator._is_running:
        raise HTTPException(400, "Pipeline not running")
    await orchestrator.stop()
    return {"message": "Pipeline stopped"}


@router.get("/status")
async def pipeline_status():
    """Get full pipeline status with all service metrics."""
    return orchestrator.get_full_status()


@router.post("/chat")
async def inject_chat(request: ChatMessageRequest):
    """Inject a chat message for analysis (testing)."""
    result = await orchestrator.inject_chat_message(request.text, request.user)
    if result:
        return result.model_dump()
    raise HTTPException(500, "Chat analysis not available")


@router.post("/analyze-frame")
async def analyze_frame():
    """Analyze a test frame (for demo/testing)."""
    import numpy as np
    # Create a test frame
    test_frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
    result = await orchestrator.analyze_single_frame(test_frame)
    return {
        "faces": len(result.faces),
        "emotions": len(result.emotions),
        "poses": len(result.poses),
        "inference_ms": result.inference_time_ms,
    }


@router.get("/events")
async def get_recent_events(last_n: int = 50):
    """Get recent events from the event bus."""
    if orchestrator.event_bus:
        events = orchestrator.event_bus.get_all_recent(last_n)
        return [e.model_dump(mode="json") for e in events]
    return []


@router.get("/events/{event_type}")
async def get_events_by_type(event_type: str, last_n: int = 20):
    """Get recent events of a specific type."""
    if orchestrator.event_bus:
        events = orchestrator.event_bus.get_history(event_type, last_n)
        return [e.model_dump(mode="json") for e in events]
    return []


@router.get("/score")
async def get_current_score():
    """Get the current highlight score."""
    if orchestrator.event_detector:
        score = orchestrator.event_detector.get_latest_score()
        return score.model_dump()
    raise HTTPException(500, "Event detector not available")


@router.get("/metrics")
async def get_metrics():
    """Get event bus metrics."""
    if orchestrator.event_bus:
        return orchestrator.event_bus.metrics
    return {}
