"""
Polyglot Microservices Client
==============================
Python FastAPI Core'un TypeScript AI Worker ve Go Render Engine
ile haberleşmesini sağlayan HTTP istemci katmanı.

Kullanım:
    from services.microservices_client import ai_worker, render_engine

    clips = await ai_worker.analyze(transcript_text)
    job = await render_engine.queue_render(video_path, out_path, start, end)
    status = await render_engine.get_status(job["job_id"])
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("microservices_client")

# ── Service URLs (override via env vars) ──────────────────────────────────────
AI_WORKER_URL    = os.environ.get("AI_WORKER_URL",    "http://localhost:3001")
RENDER_ENGINE_URL = os.environ.get("RENDER_ENGINE_URL", "http://localhost:3002")

_TIMEOUT = httpx.Timeout(60.0, connect=5.0)


# ─────────────────────────────── AI Worker ────────────────────────────────────

class AIWorkerClient:
    """TypeScript AI Agent Worker istemcisi (Chain-of-Thought klip seçimi)."""

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.get(f"{AI_WORKER_URL}/health")
                return r.status_code == 200
        except Exception:
            return False

    async def analyze(
        self,
        transcript: str,
        language: str = "tr",
        max_clips: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Transkripti TypeScript Agent'larına gönderir.
        Geri dönen FinalClip listesini döndürür.
        """
        if not await self.health():
            logger.warning("AI Worker offline, falling back to Python LLM Reasoner.")
            return await self._python_fallback(transcript, language, max_clips)

        payload = {"transcript": transcript, "language": language, "max_clips": max_clips}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{AI_WORKER_URL}/analyze", json=payload)
            resp.raise_for_status()
            data = resp.json()
            clips: List[Dict[str, Any]] = data.get("clips", [])
            logger.info(
                "AI Worker returned %d clips (analyzed=%d, reviewed=%d, finalized=%d)",
                len(clips),
                data.get("agent_log", {}).get("analyzed", "?"),
                data.get("agent_log", {}).get("reviewed", "?"),
                data.get("agent_log", {}).get("finalized", "?"),
            )
            return clips

    async def _python_fallback(
        self, transcript: str, language: str, max_clips: int
    ) -> List[Dict[str, Any]]:
        """AI Worker offline olduğunda mevcut Python LLM Reasoner'a düşer."""
        try:
            from services.llm_reasoner import LLMReasoner
            reasoner = LLMReasoner()
            results = await reasoner.get_semantic_highlights(transcript)
            return results[:max_clips]
        except Exception as e:
            logger.error("Python LLM fallback also failed: %s", e)
            return []


# ─────────────────────────── Go Render Engine ────────────────────────────────

class RenderEngineClient:
    """Go FFmpeg Render Engine istemcisi (goroutine worker pool)."""

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.get(f"{RENDER_ENGINE_URL}/health")
                return r.status_code == 200
        except Exception:
            return False

    async def queue_render(
        self,
        video_path: str,
        output_path: str,
        start: float,
        end: float,
        platform: str = "tiktok",
    ) -> Optional[Dict[str, Any]]:
        """
        Go render kuyruğuna yeni bir iş ekler.
        {'job_id': '...', 'status': 'pending'} döndürür.
        """
        if not await self.health():
            logger.warning("Go Render Engine offline, using Python render fallback.")
            return None

        payload = {
            "video_path": video_path,
            "output_path": output_path,
            "start": start,
            "end": end,
            "platform": platform,
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{RENDER_ENGINE_URL}/render", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """İş durumunu sorgular: pending | running | done | failed"""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(f"{RENDER_ENGINE_URL}/status/{job_id}")
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error("Render status check failed: %s", e)
            return None


# ── Singleton instances ───────────────────────────────────────────────────────
ai_worker     = AIWorkerClient()
render_engine = RenderEngineClient()
