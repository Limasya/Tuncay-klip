"""
Thumbnail A/B Test — Başlık ve Thumbnail A/B Testi
───────────────────────────────────────────────────
FAZ-3.2: Thumbnail ve başlık için A/B varyantları oluşturma ve test etme.

Features:
  - LLM ile başlık varyantları üretme
  - Thumbnail varyantları (farklı kesim noktaları, filtreler)
  - A/B test tracking (gösterim, tıklama, CTR)
  - Kazanan varyantı otomatik seçme
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("thumbnail_ab")


class ABVariant(BaseModel):
    """A/B test varyantı."""
    variant_id: str = ""
    variant_label: str = ""  # "A", "B", "C"...
    title: str = ""
    description: str = ""
    hashtags: List[str] = Field(default_factory=list)
    thumbnail_path: str = ""
    thumbnail_timestamp: float = 0.0  # videonun kaçıncı saniyesinden
    thumbnail_filter: str = ""  # "default", "high_contrast", "warm", "cool"
    # Metrikler
    impressions: int = 0
    clicks: int = 0
    views: int = 0
    likes: int = 0
    ctr: float = 0.0
    engagement_rate: float = 0.0
    # Durum
    is_winner: bool = False
    confidence: float = 0.0


class ABTest(BaseModel):
    """A/B test denemesi."""
    test_id: str = ""
    clip_id: str = ""
    platform: str = ""
    variants: List[ABVariant] = Field(default_factory=list)
    status: str = "active"  # active, completed, cancelled
    winner_id: str = ""
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ended_at: str = ""
    total_impressions: int = 0
    total_clicks: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ThumbnailABTest:
    """
    Thumbnail ve başlık A/B test sistemi.
    """

    # Başlık şablonları
    TITLE_TEMPLATES = [
        "{streamer} {action} — {game} {highlight}",
        "BU ANI KAÇIRMAYIN! {highlight}",
        "{streamer}'in EN {adjective} ANI — {game}",
        "{highlight} — {streamer} {game} Yayınından",
        "VIRAL: {highlight} {emoji}",
    ]

    ADJECTIVES = ["İYİ", "HARİKA", "VİRAL", "ŞAŞIRTICI", "EFSANE", "UNUTULMAZ"]
    EMOJIS = ["🔥", "😱", "💀", "😂", "🏆", "⚡", "🎮", "🎯"]

    def __init__(self, state_path: str | Path | None = None):
        self._tests: Dict[str, ABTest] = {}
        self._state_path = Path(state_path or "data/thumbnail_ab_state.json")

    async def create_test(
        self,
        clip_id: str,
        video_path: str,
        platform: str,
        streamer: str = "Tuncay",
        game: str = "Kick",
        highlight_description: str = "",
        num_variants: int = 3,
    ) -> ABTest:
        """Yeni bir A/B testi oluştur."""
        test_id = f"ab_{uuid.uuid4().hex[:8]}"

        # Başlık varyantları üret
        titles = await self._generate_title_variants(
            streamer, game, highlight_description, num_variants
        )

        # Thumbnail varyantları öner
        thumbnails = self._suggest_thumbnail_variants(video_path, num_variants)

        variants = []
        labels = [chr(65 + i) for i in range(num_variants)]  # A, B, C...
        for i in range(num_variants):
            variant = ABVariant(
                variant_id=f"{test_id}_{labels[i]}",
                variant_label=labels[i],
                title=titles[i] if i < len(titles) else f"Variant {labels[i]}",
                thumbnail_path=thumbnails[i].get("path", ""),
                thumbnail_timestamp=thumbnails[i].get("timestamp", 0.0),
                thumbnail_filter=thumbnails[i].get("filter", "default"),
            )
            variants.append(variant)

        test = ABTest(
            test_id=test_id,
            clip_id=clip_id,
            platform=platform,
            variants=variants,
        )
        self._tests[test_id] = test

        logger.info(
            "A/B test created: %s (%d variants) for clip %s",
            test_id, num_variants, clip_id[:8],
        )
        return test

    async def _generate_title_variants(
        self,
        streamer: str,
        game: str,
        highlight: str,
        count: int,
    ) -> List[str]:
        """LLM ile başlık varyantları üret."""
        try:
            from services import llm_client
            prompt = (
                f"Bir {game} yayınından viral bir klip için {count} farklı başlık öner.\n"
                f"Yayıncı: {streamer}\n"
                f"Vurgu: {highlight}\n"
                f"Her başlık 100 karakterden kısa olsun.\n"
                f"Format: her satırda bir başlık, numara yok."
            )
            result = await llm_client.generate(prompt, max_tokens=300)
            if result:
                lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
                # Numaraları temizle
                cleaned = []
                for l in lines:
                    l = l.lstrip("0123456789.()-) ")
                    if l:
                        cleaned.append(l[:100])
                if len(cleaned) >= count:
                    return cleaned[:count]
        except Exception as e:
            logger.warning("LLM title generation failed: %s", e)

        # Fallback: şablonlardan üret
        templates = random.sample(self.TITLE_TEMPLATES, min(count, len(self.TITLE_TEMPLATES)))
        return [
            t.format(
                streamer=streamer,
                game=game,
                highlight=highlight or "Efsane An",
                action="Patladı",
                adjective=random.choice(self.ADJECTIVES),
                emoji=random.choice(self.EMOJIS),
            )
            for t in templates
        ]

    def _suggest_thumbnail_variants(
        self, video_path: str, count: int
    ) -> List[Dict[str, Any]]:
        """Thumbnail için farklı zaman noktaları ve filtreler öner."""
        variants = []
        filters = ["default", "high_contrast", "warm", "cool", "vibrant"]

        for i in range(count):
            # Farklı zaman noktaları: 10%, 30%, 50%, 70%, 90%
            timestamps = [0.1, 0.3, 0.5, 0.7, 0.9]
            ts = timestamps[i % len(timestamps)]
            filt = filters[i % len(filters)]

            variants.append({
                "path": "",  # Gerçek thumbnail yolu yükleme sırasında oluşur
                "timestamp": ts,
                "filter": filt,
            })

        return variants

    async def record_impression(self, test_id: str, variant_id: str):
        """Bir gösteriyi kaydet."""
        test = self._tests.get(test_id)
        if not test:
            return
        for v in test.variants:
            if v.variant_id == variant_id:
                v.impressions += 1
                test.total_impressions += 1
                v.ctr = v.clicks / max(1, v.impressions) * 100
                break

    async def record_click(self, test_id: str, variant_id: str):
        """Bir tıklamayı kaydet."""
        test = self._tests.get(test_id)
        if not test:
            return
        for v in test.variants:
            if v.variant_id == variant_id:
                v.clicks += 1
                test.total_clicks += 1
                v.ctr = v.clicks / max(1, v.impressions) * 100
                break

    async def record_engagement(
        self, test_id: str, variant_id: str,
        views: int = 0, likes: int = 0,
    ):
        """Engagement metriklerini kaydet."""
        test = self._tests.get(test_id)
        if not test:
            return
        for v in test.variants:
            if v.variant_id == variant_id:
                v.views += views
                v.likes += likes
                v.engagement_rate = (v.likes + v.clicks) / max(1, v.views) * 100
                break

    def get_winner(self, test_id: str) -> Optional[ABVariant]:
        """Kazanan varyantı belirle."""
        test = self._tests.get(test_id)
        if not test:
            return None

        # Minimum gösterim eşiği
        min_impressions = 50
        eligible = [v for v in test.variants if v.impressions >= min_impressions]

        if not eligible:
            return None

        # CTR'ye göre kazananı seç
        winner = max(eligible, key=lambda v: v.ctr)

        # İstatistiksel anlamlılık kontrolü (basit)
        if len(eligible) >= 2:
            sorted_v = sorted(eligible, key=lambda v: v.ctr, reverse=True)
            top2_diff = sorted_v[0].ctr - sorted_v[1].ctr
            if top2_diff > 1.0:  # %1'den fazla fark
                winner.confidence = min(0.95, 0.5 + top2_diff * 0.1)
                winner.is_winner = True
                test.winner_id = winner.variant_id
                test.status = "completed"
                test.ended_at = datetime.now(timezone.utc).isoformat()

        return winner

    def get_test(self, test_id: str) -> Optional[ABTest]:
        return self._tests.get(test_id)

    def get_active_tests(self) -> List[ABTest]:
        return [t for t in self._tests.values() if t.status == "active"]

    def get_tests_by_clip(self, clip_id: str) -> List[ABTest]:
        return [t for t in self._tests.values() if t.clip_id == clip_id]

    def get_stats(self) -> Dict[str, Any]:
        active = sum(1 for t in self._tests.values() if t.status == "active")
        completed = sum(1 for t in self._tests.values() if t.status == "completed")
        total_impressions = sum(t.total_impressions for t in self._tests.values())
        total_clicks = sum(t.total_clicks for t in self._tests.values())

        return {
            "total_tests": len(self._tests),
            "active": active,
            "completed": completed,
            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "overall_ctr": round(total_clicks / max(1, total_impressions) * 100, 2),
        }

    # ── Persistence ──

    async def save(self) -> None:
        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "tests": [t.model_dump() for t in list(self._tests.values())[-100:]],
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._state_path.with_suffix(".tmp")
        await asyncio.to_thread(
            temp.write_text,
            json.dumps(state, ensure_ascii=False, indent=2, default=str),
            "utf-8",
        )
        await asyncio.to_thread(temp.replace, self._state_path)

    async def load(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = await asyncio.to_thread(self._state_path.read_text, encoding="utf-8")
            state = json.loads(data)
            for td in state.get("tests", []):
                test = ABTest(**td)
                self._tests[test.test_id] = test
        except Exception as e:
            logger.warning("Thumbnail A/B state load failed: %s", e)


# Singleton
thumbnail_ab_test = ThumbnailABTest()
