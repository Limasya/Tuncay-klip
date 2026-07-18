"""
Zero-Bandwidth Clip Engine — LLM Analiz
────────────────────────────────────────
LLM ile VOD analizi, prompt olusturma, JSON parse.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

from .models import ClipSuggestion, VODAnalysis
from .community_clips import (
    calculate_community_confidence,
    detect_clip_clusters,
    estimate_clip_position,
)

logger = logging.getLogger("zero_bandwidth_clipper")


async def analyze_with_llm(
    metadata: dict[str, Any],
    community_clips: list[dict[str, Any]],
    transcription_text: Optional[str] = None,
    format_clips_fn=None,
) -> dict[str, Any]:
    """LLM ile VOD analizi yap.

    format_clips_fn: community_clips modulundeki format_clips_for_llm fonksiyonu.
    """
    if format_clips_fn is None:
        from .community_clips import format_clips_for_llm
        format_clips_fn = format_clips_for_llm

    title = str(metadata.get("session_title") or metadata.get("title") or "")
    duration_raw = metadata.get("duration", 0)
    duration_sec = float(duration_raw) if duration_raw else 3600
    if duration_sec > 86400:
        duration_sec = duration_sec / 1000.0
    category = str(metadata.get("category") or "")

    clips_text = format_clips_fn(
        community_clips,
        vod_start_time=str(metadata.get("start_time") or metadata.get("created_at", "")),
        vod_duration=duration_sec,
    )

    system_prompt = """Sen bir Kick.com clip analiz uzmanisin. Verilen VOD bilgilerine bakarak viral potansiyeli yuksek clip anlarini tespit et.

Kurallar:
- Her clip icin baslangic ve bitis suresi belirt (saniye cinsinden, VOD basindan itibaren)
- Tahmini baslangic/bitis suresi kullan (VOD metadata'sindan hesapla)
- Confidence: 0.0-1.0 arasi, ne kadar emin oldugunu goster
- Sadece JSON don, baska bir sey yazma

Format:
{
  "summary": "VOD hakkinda kisa ozet",
  "highlights": [
    {
      "start_sec": 120,
      "end_sec": 150,
      "title": "Clip basligi",
      "reason": "Neden viral olabilir",
      "confidence": 0.85
    }
  ]
}"""

    user_parts = [
        f"VOD: {title}",
        f"Sure: {duration_sec:.0f} saniye",
        f"Kategori: {category}",
    ]

    if clips_text:
        user_parts.append(clips_text)

    if transcription_text:
        # Transkripsiyon cok uzunsa kisalt
        if len(transcription_text) > 3000:
            transcription_text = transcription_text[:3000] + "... (kesildi)"
        user_parts.append(f"\nSes transkripsiyonu:\n{transcription_text}")

    user_prompt = "\n".join(user_parts)

    # LLM ile analiz
    result = await _call_llm(system_prompt, user_prompt)
    return result


async def _call_llm(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """LLM cagrisi yap ve JSON sonucunu parse et."""
    try:
        from services.llm_client import generate as llm_generate

        response = await llm_generate(
            system=system_prompt,
            user=user_prompt,
            temperature=0.3,
            max_tokens=2000,
        )

        if not response:
            return {"summary": "LLM yanit vermedi", "highlights": []}

        return _parse_llm_response(response)

    except ImportError:
        logger.warning("LLM client mevcut degil")
        return {"summary": "LLM client mevcut degil", "highlights": []}
    except Exception as e:
        logger.error("LLM analiz hatasi: %s", e)
        return {"summary": f"LLM hatasi: {e}", "highlights": []}


def _parse_llm_response(text: str) -> dict[str, Any]:
    """LLM yanitindan JSON cikar."""
    # Direkt JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Markdown kod blogu temizle
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # { ... } arasini cikar
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {"summary": "JSON parse edilemedi", "highlights": []}


def build_clip_suggestions(
    vod_id: str,
    vod_url: str,
    metadata: dict[str, Any],
    llm_result: dict[str, Any],
    community_clips: list[dict[str, Any]],
) -> VODAnalysis:
    """LLM sonuclari + community clips ClipSuggestion listesine donustur."""
    title = str(metadata.get("session_title") or metadata.get("title") or "")
    duration_raw = metadata.get("duration", 0)
    duration_sec = float(duration_raw) if duration_raw else 3600
    if duration_sec > 86400:
        duration_sec = duration_sec / 1000.0
    category = str(metadata.get("category") or "")
    created_at = str(metadata.get("created_at") or "")
    vod_start = str(metadata.get("start_time") or created_at)

    clips: list[ClipSuggestion] = []

    # LLM clip'leri
    highlights = llm_result.get("highlights", [])
    for h in highlights:
        start = float(h.get("start_sec", 0))
        end = float(h.get("end_sec", start + 30))
        clip = ClipSuggestion(
            clip_id=f"llm_{vod_id}_{int(start)}",
            title=str(h.get("title", "LLM Clip")),
            description=str(h.get("reason", "")),
            start_time=start,
            end_time=end,
            duration=end - start,
            confidence=float(h.get("confidence", 0.7)),
            reason=str(h.get("reason", "LLM tahmini")),
            source="llm_guess",
        )
        clips.append(clip)

    # Community clip'leri ekle
    if community_clips:
        clusters = detect_clip_clusters(community_clips, vod_start)
        max_views = max((c.get("views", 0) for c in community_clips), default=0)

        for i, c in enumerate(community_clips):
            pos = estimate_clip_position(c, vod_start)
            cluster_size = clusters[i] if i < len(clusters) else 1
            conf = calculate_community_confidence(
                c.get("views", 0), c.get("likes", 0), max_views, cluster_size,
            )
            clip_duration = float(c.get("duration", 30))
            clip_start = pos if pos is not None else 0.0

            clip = ClipSuggestion(
                clip_id=f"community_{c.get('clip_id', i)}",
                title=str(c.get("title", "Community Clip")),
                description=f"Topluluk tarafindan kesildi: {c.get('creator', 'Bilinmiyor')}",
                start_time=clip_start,
                end_time=clip_start + clip_duration,
                duration=clip_duration,
                confidence=conf,
                reason=f"Topluluk clipi (izlenme: {c.get('views', 0)})",
                source="community_clip",
                community_views=c.get("views", 0),
                community_likes=c.get("likes", 0),
                community_creator=str(c.get("creator", "")),
                estimated_position_sec=clip_start,
                position_confidence="approximate" if pos is not None else "none",
            )
            clips.append(clip)

    clips.sort(key=lambda c: c.confidence, reverse=True)

    return VODAnalysis(
        vod_id=vod_id,
        vod_url=vod_url,
        title=title,
        duration=duration_sec,
        category=category,
        created_at=created_at,
        ai_summary=llm_result.get("summary", ""),
        highlights_detected=highlights,
        clips=clips,
        analysis_time_sec=0.0,
        bandwidth_used_kb=0.0,
    )
