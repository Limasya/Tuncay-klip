"""
Zero-Bandwidth Clip Engine — Veri Modelleri
───────────────────────────────────────────
ClipSuggestion ve VODAnalysis dataclass'lari.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ClipSuggestion:
    """Tek bir clip önerisi — topluluk clip'lerinden veya LLM tahmininden."""
    clip_id: str
    title: str
    description: str
    start_time: float
    end_time: float
    duration: float
    confidence: float
    reason: str
    source: str = "llm_guess"  # "community_clip" | "llm_guess" | "hybrid"
    platform: str = "tiktok"
    thumbnail_hint: str = ""
    tags: list[str] = field(default_factory=list)
    community_views: int = 0
    community_likes: int = 0
    community_creator: str = ""
    estimated_position_sec: float = 0.0
    position_confidence: str = "none"  # "none" | "approximate" | "exact"


@dataclass
class VODAnalysis:
    """Bir VOD'un AI analiz sonucu."""
    vod_id: str
    vod_url: str
    title: str
    duration: float
    category: str
    created_at: str
    ai_summary: str
    highlights_detected: list[dict[str, Any]]
    clips: list[ClipSuggestion]
    analysis_time_sec: float
    bandwidth_used_kb: float
    analyzed_at: str = ""

    def __post_init__(self):
        if not self.analyzed_at:
            self.analyzed_at = datetime.now(timezone.utc).isoformat()
