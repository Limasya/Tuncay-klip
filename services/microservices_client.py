"""
Polyglot Microservices Client
==============================
Python FastAPI Core'un TypeScript AI Worker ile haberleşmesini sağlayan
HTTP istemci katmanı.

Kullanım:
    from services.microservices_client import ai_worker

    clips = await ai_worker.analyze(transcript_text)

NOTE: Go render_engine was removed (dead code). All rendering is handled
by Python's services/social_video_generator.py and render_pipeline.py.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import httpx

logger = logging.getLogger("microservices_client")

# ── Service URLs (override via env vars) ──────────────────────────────────────
AI_WORKER_URL = os.environ.get("AI_WORKER_URL", "http://localhost:3001")

_TIMEOUT = httpx.Timeout(60.0, connect=5.0)


# ─────────────────────────────── AI Worker ────────────────────────────────────

class AIWorkerClient:
    """TypeScript AI Agent Worker istemcisi (Chain-of-Thought klip seçimi).

    DESIGN DECISION: ai_worker owns its own LLM client (llmClient.ts) and
    does NOT route through Python's LLM facade. See ai_worker/src/llmClient.ts
    for rationale. Python fallback activates only when this service is offline.
    """

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


# ── Singleton instances ───────────────────────────────────────────────────────
ai_worker = AIWorkerClient()
