"""
AI-Powered Clip Skorlama + Kancalama Tespiti
─────────────────────────────────────────────
LLM ile clip metadata'sını analiz eder:
  - Kancalama (hook) gücü — ilk bakışta dikkat çekiyor mu?
  - Viral potansiyel — paylaşılma oranı
  - İçerik kalitesi — düzenleme potansiyeli
  - Engagement oranı — views/likes ilişkisi
  - Edit potansiyeli — otomatik edit ile ne kadar iyileştirilebilir?

Python math + LLM hybrid: LLM yoksa fallback matematiksel skorlama.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("clip_scorer")


class ClipScorer:
    """
    AI-powered clip skorlama servisi.
    LLM varsa: çok boyutlu analiz + kancalama tespiti.
    LLM yoksa: gelişmiş matematiksel skorlama (fallback).
    """

    def __init__(self):
        self._llm_available = None

    def _is_llm_available(self) -> bool:
        if self._llm_available is not None:
            return self._llm_available
        try:
            from services.llm_engine import llm_engine
            self._llm_available = len(llm_engine._providers) > 0
        except Exception:
            self._llm_available = False
        return self._llm_available

    async def score_clip(self, clip: dict[str, Any]) -> dict[str, Any]:
        """
        Tek bir klibi AI ile puanlandır.
        """
        if self._is_llm_available():
            return await self._score_with_llm(clip)
        return self._score_with_math(clip)

    async def score_batch(self, clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Toplu skorlama — LLM varsa batch prompt, yoksa math.
        """
        if not clips:
            return []

        if self._is_llm_available():
            return await self._batch_score_with_llm(clips)

        # Fallback: math ile hızlı skorla
        scored = [self._score_with_math(c) for c in clips]
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        return scored

    # ── LLM Scoring ──────────────────────────────────────────────

    async def _score_with_llm(self, clip: dict[str, Any]) -> dict[str, Any]:
        """LLM ile tek klip skorlama."""
        from services.llm_engine import llm_engine

        title = clip.get("title", "")
        views = clip.get("views", 0)
        likes = clip.get("likes", 0)
        duration = clip.get("duration", 0)
        creator = clip.get("creator_username", "")

        prompt = f"""Analyze this clip for TikTok, Instagram Reels, YouTube Shorts, and X virality (2026 research).

TITLE: {title}
VIEWS: {views}
LIKES: {likes}
DURATION: {duration}s
CREATOR: {creator}

═══ 2026 SHORT-FORM VIDEO RESEARCH ═══

HOOK FORMATS (ranked by effectiveness):
1. Instant-promise: Clear value in 2 seconds ("This trick gets you hired")
2. Contradiction: Challenge expectations ("Stop studying — it's ruining your career")
3. Before-and-after: Quick visual transformation (3s before, 3s after)
4. List-with-twist: Multiple tips + surprise ending
5. Visual confession: Raw, intimate, vulnerable tone
6. Price tag: Specific number hook ("$0 to $10K in 30 days")
7. Pattern interrupt: Unexpected scene/sound change

PLATFORM ALGORITHM SIGNALS:
- TikTok: Watch completion > DM shares > Likes. Raw & Fast aesthetic wins. Trending sounds critical. 21-34s sweet spot.
- Instagram Reels: DM shares (3-5x weighted) > Saves > Comments > Completion. Aesthetic & Curated. 15-30s sweet spot. No TikTok watermarks (penalized).
- YouTube Shorts: Watch time + CTR. Utility & Search focused. 15-60s. Original audio preferred.
- X/Twitter: Conversation starters. 2:20 max. 16:9 or 1:1 works.

DM SHARE TRIGGERS (strongest signal for Reels in 2026):
- "Tag someone who needs this"
- "Send this to your friend who..."
- Relatable moments that make people think of someone
- Last 5 seconds = design for shares (not likes)

EDIT PACING RULES:
- Scene change every 2-3s
- Zoom/jump-cut every 3-5s
- No intros/outros (kills completion rate)
- 85% watch without sound → animated captions mandatory
- Implied CTA beats direct CTA by 2x

SAFE ZONES (cross-platform):
- TikTok: top 15%, bottom 35% reserved for UI
- Reels: top 12%, bottom 30% reserved for UI
- Shorts: top 10%, bottom 25% reserved for UI
- Caption safe: center 60% (platform-agnostic)

Evaluate on:
- Which of the 7 hook formats this clip uses (or could use)
- DM share potential (would someone send this to a friend?)
- Platform-specific scores (TikTok vs Reels vs Shorts)
- Completion rate potential per platform
- Scene density and edit pacing quality
- Whether hook type matches platform preference

Return ONLY this JSON (no other text):
{{
  "hook_type": "instant_promise|contradiction|before_after|list_with_twist|visual_confession|price_tag|pattern_interrupt|hot_take|none",
  "hook_strength": 0-100,
  "hook_reason": "brief explanation of hook quality",
  "emotional_trigger": "fear|empathy|outrage|humor|curiosity|none",
  "tiktok_score": 0-100,
  "reels_score": 0-100,
  "shorts_score": 0-100,
  "x_score": 0-100,
  "dm_share_potential": 0-100,
  "dm_share_reason": "would someone send this? why or why not?",
  "optimal_duration_tiktok": 21-34,
  "optimal_duration_reels": 15-30,
  "caption_style": "hormozi|clean|karaoke|minimal|none",
  "stock_hook_needed": false,
  "scene_density": "high|medium|low",
  "viral_potential": 0-100,
  "viral_reason": "brief viral potential explanation",
  "edit_potential": 0-100,
  "category": "funny|exciting|rage|fail|skill|wholesome|educational|other",
  "best_hook_moment": "predicted strongest moment based on title/duration",
  "suggested_hook_format": "which of the 7 hook formats works best for this clip and why",
  "send_trigger": "specific text/action for last 5 seconds to maximize DM shares",
  "suggested_edit": "Platform-specific edit suggestions with exact timing (9:16 crop, scene changes at Xs, animated captions, safe zones, zoom at Ys)",
  "overall_score": 0-100,
  "grade": "A|B|C|D",
  "verdict": "edit|watch|skip",
  "meme_potential": 0-100,
  "sfx_potential": 0-100
}}"""

        try:
            result = await llm_engine.generate(
                prompt,
                language="tr",
                max_tokens=512,
                temperature=0.3,
                use_cache=True,
            )

            # JSON parse
            parsed = self._parse_llm_json(result)
            if parsed:
                # Math fallback ile birleştir
                math_score = self._score_with_math(clip)
                parsed["math_score"] = math_score.get("score", 0)

                # Ağırlıklı ortalama: %60 LLM + %40 math
                final_score = (
                    parsed.get("overall_score", 50) * 0.6
                    + math_score.get("score", 50) * 0.4
                )
                parsed["score"] = round(min(100, max(0, final_score)), 1)
                parsed["grade"] = self._score_to_grade(parsed["score"])
                parsed["verdict"] = self._score_to_verdict(parsed["score"])
                parsed["scoring_method"] = "llm"
                return parsed

        except Exception as e:
            logger.debug("LLM scoring failed, falling back to math: %s", e)

        return self._score_with_math(clip)

    async def _batch_score_with_llm(self, clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Toplu LLM skorlama — 5'er 5'er gruplar halinde."""
        all_scored = []
        batch_size = 5

        for i in range(0, len(clips), batch_size):
            batch = clips[i:i + batch_size]

            # Batch prompt
            clip_summaries = []
            for j, c in enumerate(batch):
                clip_summaries.append(
                    f"[{j+1}] Başlık: {c.get('title','?')} | "
                    f"İzlenme: {c.get('views',0)} | Beğeni: {c.get('likes',0)} | "
                    f"Süre: {c.get('duration',0)}s | Creator: {c.get('creator_username','?')}"
                )

            prompt = f"""Analyze these {len(batch)} clips for TikTok, Reels, Shorts, X virality (2026 research):

{chr(10).join(clip_summaries)}

For each clip, return a JSON array with platform-specific scoring:

[
  {{
    "index": 1,
    "hook_type": "instant_promise|contradiction|before_after|list_with_twist|visual_confession|price_tag|pattern_interrupt|hot_take|none",
    "hook_strength": 0-100,
    "emotional_trigger": "fear|empathy|outrage|humor|curiosity|none",
    "tiktok_score": 0-100,
    "reels_score": 0-100,
    "shorts_score": 0-100,
    "x_score": 0-100,
    "dm_share_potential": 0-100,
    "optimal_duration_tiktok": 21-34,
    "optimal_duration_reels": 15-30,
    "caption_style": "hormozi|clean|karaoke|minimal|none",
    "stock_hook_needed": false,
    "scene_density": "high|medium|low",
    "viral_potential": 0-100,
    "edit_potential": 0-100,
    "category": "funny|exciting|rage|fail|skill|wholesome|educational|other",
    "best_hook_moment": "strongest moment",
    "suggested_hook_format": "best hook format for this clip",
    "send_trigger": "text for last 5s to maximize DM shares",
    "suggested_edit": "Platform-specific edit with timing",
    "overall_score": 0-100,
    "meme_potential": 0-100,
    "sfx_potential": 0-100
  }},
  ...
]

Return ONLY the JSON array, no other text."""

            try:
                from services.llm_engine import llm_engine
                result = await llm_engine.generate(
                    prompt, language="tr", max_tokens=1024,
                    temperature=0.3, use_cache=True,
                )

                parsed_list = self._parse_llm_json_array(result)
                if parsed_list and len(parsed_list) == len(batch):
                    for j, (clip, llm_data) in enumerate(zip(batch, parsed_list)):
                        math_score = self._score_with_math(clip)
                        final_score = (
                            llm_data.get("overall_score", 50) * 0.6
                            + math_score.get("score", 50) * 0.4
                        )
                        clip.update(llm_data)
                        clip["score"] = round(min(100, max(0, final_score)), 1)
                        clip["grade"] = self._score_to_grade(clip["score"])
                        clip["verdict"] = self._score_to_verdict(clip["score"])
                        clip["scoring_method"] = "llm_batch"
                        all_scored.append(clip)
                    continue

            except Exception as e:
                logger.debug("LLM batch scoring failed: %s", e)

            # Fallback: bu batch'i math ile skorla
            for c in batch:
                all_scored.append(self._score_with_math(c))

        all_scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        return all_scored

    # ── Math Scoring (Fallback + LLM combo) ──────────────────────

    def _score_with_math(self, clip: dict[str, Any]) -> dict[str, Any]:
        """
        Geliştirilmiş matematiksel skorlama.
        Kancalama, engagement, potansiyel odaklı.
        """
        views = clip.get("views", 0) or 0
        likes = clip.get("likes", 0) or 0
        duration = clip.get("duration", 0) or 0
        title = (clip.get("title", "") or "").lower()
        created_at = clip.get("created_at", "")

        # ── 1. Engagement Skoru (views/likes oranı — en önemli) ──
        if views > 0:
            like_ratio = likes / views
            # %10+ = muhteşem, %5+ = iyi, %2+ = normal, %1- = düşük
            if like_ratio >= 0.10:
                engagement = 100
            elif like_ratio >= 0.05:
                engagement = 85
            elif like_ratio >= 0.02:
                engagement = 65
            elif like_ratio >= 0.01:
                engagement = 45
            else:
                engagement = 25
            # Views mutlak değeri de önemli (1K views + %5 like > 10 views + %5 like)
            view_bonus = min(20, math.log10(max(views, 1)) * 5)
            engagement = min(100, engagement + view_bonus)
        else:
            engagement = 10

        # ── 2. Kancalama (Hook) Skoru ──
        hook = self._calculate_hook_score(title, duration, views, likes)

        # ── 3. Viral Potansiyel ──
        viral = self._calculate_viral_potential(title, views, likes, duration)

        # ── 4. Edit Potansiyeli ──
        edit_pot = self._calculate_edit_potential(duration, title)

        # ── Ağırlıklı toplam ──
        score = (
            engagement * 0.35      # Engagement en önemli
            + hook * 0.30          # Kancalama çok önemli
            + viral * 0.20         # Viral potansiyel
            + edit_pot * 0.15      # Edit potansiyeli
        )

        score = round(min(100, max(0, score)), 1)

        # Kategori tespiti
        category = self._detect_category(title)

        # Platform-spesifik skorlar (2026 research)
        platform_scores = self._calculate_platform_scores(
            title, duration, hook, viral, engagement,
        )

        # DM share potansiyeli (Reels 2026 #1 sinyal)
        dm_share_potential = self._calculate_dm_share_potential(title, category, hook)

        # Send trigger — son 5 saniye için DM paylaşım metni
        send_trigger = self._generate_send_trigger(category, title)

        return {
            "clip_id": clip.get("clip_id", ""),
            "clip_url": clip.get("clip_url") or clip.get("url", ""),
            "title": clip.get("title", ""),
            "views": clip.get("views", 0),
            "likes": clip.get("likes", 0),
            "duration": clip.get("duration", 0),
            "score": score,
            "grade": self._score_to_grade(score),
            "verdict": self._score_to_verdict(score),
            "hook_score": round(hook, 1),
            "hook_reason": self._get_hook_reason(hook, title, duration),
            "viral_potential": round(viral, 1),
            "content_quality": round(edit_pot, 1),
            "edit_potential": round(edit_pot, 1),
            "category": category,
            "best_hook_moment": self._guess_hook_moment(title, duration),
            "suggested_edit": self._suggest_edit(duration, category, edit_pot),
            "tiktok_score": platform_scores["tiktok_score"],
            "reels_score": platform_scores["reels_score"],
            "shorts_score": platform_scores["shorts_score"],
            "x_score": platform_scores["x_score"],
            "dm_share_potential": dm_share_potential,
            "send_trigger": send_trigger,
            "meme_potential": self._calculate_meme_potential(title, category, hook, viral),
            "sfx_potential": self._calculate_sfx_potential(title, category, hook, viral),
            "scoring_method": "math",
            "breakdown": {
                "engagement": round(engagement, 1),
                "hook": round(hook, 1),
                "viral": round(viral, 1),
                "edit_potential": round(edit_pot, 1),
            },
        }

    def _calculate_hook_score(self, title: str, duration: float, views: int, likes: int) -> float:
        """
        Kancalama (hook) skoru hesapla — TikTok/Instagram Reels 2026 best practices.
        7 hook formatından hangisi kullanıldığını tahmin et.
        Hot Take and Investigator hooks beat Story hooks by 20x.
        """
        score = 30  # baz

        # ── 7 hook formatı (2026 Reels research) ──
        # instant_promise: "This trick gets you hired"
        # contradiction: "Stop studying — it's ruining your career"
        # before_after: "Glass skin in 3 minutes"
        # list_with_twist: "5 mistakes you're making"
        # visual_confession: "I failed my driving test 4 times"
        # price_tag: "$0 to $10K in 30 days"
        # pattern_interrupt: unexpected scene/sound change
        hook_format_patterns = {
            # instant_promise
            "pov": 15, "when ": 12, "this is why": 12, "this trick": 14,
            "this will": 13, "stop scrolling": 15, "everyone needs to know": 13,
            "you need to know": 13, "the secret to": 14, "how to": 11,
            # contradiction
            "unpopular opinion": 14, "hot take": 15, "the truth about": 12,
            "stop doing": 13, "i quit": 12, "i regret": 11,
            "contrary to": 12, "myth": 11, "wrong about": 12,
            # before_after / transformation
            "before and after": 13, "transformation": 12, "glow up": 11,
            "then vs now": 12, "wait for it": 14,
            # list_with_twist
            "5 ways": 13, "top 5": 12, "list": 8, "things you": 11,
            "reasons why": 12,
            # visual_confession
            "i failed": 12, "confession": 11, "honest truth": 11,
            "vulnerable": 11, "real talk": 11, "story time": 11,
            # price_tag
            "$": 13, "₺": 13, "dollars": 12, "money": 10,
            "generated": 11, "i made": 12, "i earned": 12,
            # pattern_interrupt / curiosity_gap
            "you won't believe": 12, "no one talks about": 13, "nobody": 10,
            "imagine": 11, "tell me you're": 12, "it's giving": 11,
            "not me": 10, "the way": 10, "lowkey": 10, "highkey": 10,
            "bestie": 10, "main character": 13,
            # general gaming/streamer hooks
            "insane": 12, "crazy": 11, "epic": 11, "clutch": 12, "pog": 12,
            "rage": 11, "best": 10, "huge": 11, "amazing": 11, "reaction": 11,
            "fail": 11, "win": 10, "ace": 12, "headshot": 12, "flick": 12,
            "destroy": 11, "wrecked": 11, "laugh": 10, "scream": 10,
        }

        title_lower = title.lower()
        pattern_bonus = 0
        for pattern, bonus in hook_format_patterns.items():
            if pattern in title_lower:
                pattern_bonus = max(pattern_bonus, bonus)

        if pattern_bonus > 0:
            score += pattern_bonus

        # ── Strong gaming/streamer hook words ──
        strong_hooks = {
            "insane", "crazy", "epic", "clutch", "pog", "rage", "funny",
            "best", "huge", "amazing", "reaction", "fail", "win", "ace",
            "headshot", "flick", "destroy", "wrecked", "laugh", "scream",
            "wtb", "gg", "viral", "highlight", "tuncay",
        }
        weak_words = {"boring", "afk", "sleep", "zzz", "nothing", "idle"}

        words = set(title.split())
        strong_count = len(words & strong_hooks)
        weak_count = len(words & weak_words)

        if strong_count >= 3:
            score += 30
        elif strong_count >= 2:
            score += 20
        elif strong_count >= 1:
            score += 12
        else:
            score += 5

        if weak_count > 0:
            score -= weak_count * 10

        # ── Direct question or bold statement (engagement bait) ──
        if "?" in title:
            score += 8
        if "!" in title:
            score += 5

        # ── Platform-spesifik duration bonus (2026 research) ──
        # TikTok: 21-34sn sweet spot
        # Reels: 15-30sn sweet spot
        # Shorts: 15-60sn sweet spot
        # X: 30-90sn
        if 21 <= duration <= 34:
            score += 25  # TikTok sweet spot (en güçlü)
        elif 15 <= duration <= 30:
            score += 22  # Reels sweet spot
        elif 15 <= duration <= 60:
            score += 18  # Shorts sweet spot
        elif 30 <= duration <= 90:
            score += 12  # X sweet spot
        elif 15 <= duration <= 45:
            score += 15  # genel short-form optimal
        elif 5 <= duration <= 15:
            score += 8   # kısa ama idare eder
        elif 45 < duration <= 60:
            score += 5   # sınırda
        elif duration < 10:
            score -= 5   # hook geliştirmek için çok kısa
        elif duration > 60:
            score -= 10  # short-form platformlarda uzun ceza
        elif duration > 120:
            score -= 20  # çok uzun

        # ── Title length — TikTok favors concise ──
        if 5 <= len(title) <= 40:
            score += 10
        elif len(title) > 50:
            score -= 5

        # ── Emoji / caps — attention-grabbing ──
        if any(c.isupper() for c in title if c.isalpha()):
            score += 5

        emoji_count = sum(1 for c in title if ord(c) > 0x1F600)
        if emoji_count > 0:
            score += 5

        return min(100, max(0, score))

    def _calculate_viral_potential(self, title: str, views: int, likes: int, duration: float) -> float:
        """Viral potansiyel skoru."""
        score = 30

        # Views momentum — az views ama yüksek like ratio = viral adayı
        if views > 0 and likes > 0:
            ratio = likes / views
            if ratio > 0.08 and views < 100:
                score += 35  # az views ama çok like = viral adayı
            elif ratio > 0.05:
                score += 25
            elif ratio > 0.02:
                score += 15

        # Views mutlak değer
        if views > 1000:
            score += 20
        elif views > 100:
            score += 15
        elif views > 50:
            score += 10
        elif views > 20:
            score += 5

        # Kısa süre = daha fazla paylaşım
        if duration <= 30:
            score += 10
        elif duration <= 60:
            score += 5

        # Viral kelime bonusu
        viral_words = {"insane", "crazy", "epic", "pog", "viral", "best", "reaction"}
        if any(w in title.lower() for w in viral_words):
            score += 10

        return min(100, max(0, score))

    def _calculate_edit_potential(self, duration: float, title: str) -> float:
        """Edit potansiyeli skoru — düzenlemeyle ne kadar iyileştirilebilir."""
        score = 50  # baz

        if 15 <= duration <= 60:
            score += 25  # ideal edit süresi
        elif 5 <= duration <= 90:
            score += 15
        elif duration > 120:
            score -= 10

        # Başlık anlamlıysa edit daha kolay
        if len(title) > 5:
            score += 10

        return min(100, max(0, score))

    def _calculate_meme_potential(self, title: str, category: str, hook: float, viral: float) -> float:
        """Meme overlay potansiyeli — bu klip meme/fotoğraf overlay ile ne kadar iyileştirilebilir."""
        score = 40  # baz

        # Komik/heyecan verici kategorilerde meme daha etkili
        if category in ("funny", "exciting", "fail"):
            score += 25
        elif category in ("rage", "wholesome"):
            score += 15

        # Güçlü hook = meme ile desteklenebilir
        if hook > 70:
            score += 15
        elif hook > 50:
            score += 10

        # Viral potansiyeli yüksekse meme = paylaşım tetikleyici
        if viral > 70:
            score += 15
        elif viral > 50:
            score += 10

        # Başlıkta meme için uygun kelimeler
        meme_words = {"funny", "laugh", "reaction", "fail", "clutch", "epic", "rage", "pog"}
        if any(w in title.lower() for w in meme_words):
            score += 10

        return min(100, max(0, score))

    def _calculate_sfx_potential(self, title: str, category: str, hook: float, viral: float) -> float:
        """SFX potansiyeli — bu klip ses efektleri ile ne kadar iyileştirilebilir."""
        score = 35  # baz

        # Heyecan/skill kategorilerinde SFX çok etkili
        if category in ("exciting", "skill"):
            score += 30
        elif category in ("funny", "fail"):
            score += 20
        elif category in ("rage", "wholesome"):
            score += 10

        # Güçlü hook noktaları = SFX tetikleme anları
        if hook > 70:
            score += 20
        elif hook > 50:
            score += 12

        # Viral potansiyeli yüksekse SFX kaliteyi artırır
        if viral > 70:
            score += 15
        elif viral > 50:
            score += 8

        # Başlıkta ses efektine uygun kelimeler
        sfx_words = {"insane", "boom", "clutch", "ace", "headshot", "destroy", "scream", "jumpscare"}
        if any(w in title.lower() for w in sfx_words):
            score += 10

        return min(100, max(0, score))

    def _detect_category(self, title: str) -> str:
        """Başlıktan kategori tespiti."""
        title_lower = title.lower()
        categories = {
            "funny": ["funny", "laugh", "gulme", "komik", "lol", "lmao", "haha"],
            "exciting": ["insane", "crazy", "epic", "clutch", "pog", "ace", "highlight"],
            "rage": ["rage", "angry", "scream", "kiz", "sinir"],
            "fail": ["fail", "dead", "olu", "bitti"],
            "skill": ["skill", "flick", "headshot", "carry", "mvp"],
            "wholesome": ["wholesome", "cute", "tatli", "sevgi"],
        }
        for cat, keywords in categories.items():
            if any(k in title_lower for k in keywords):
                return cat
        return "other"

    def _get_hook_reason(self, hook_score: float, title: str, duration: float) -> str:
        """Kancalama skoru için kısa açıklama."""
        if hook_score >= 80:
            return f"Çok güçlü kancalama! Başlık: '{title[:30]}...' + süre: {duration}s"
        elif hook_score >= 60:
            return f"Güçlü kancalama. Başlık dikkat çekici, süre uygun."
        elif hook_score >= 40:
            return f"Orta kancalama. Başlık iyileştirilebilir."
        else:
            return f"Düşük kancalama. Başlık ve süre optimizasyonu gerekli."

    def _guess_hook_moment(self, title: str, duration: float) -> str:
        """En güçlü anı tahmin et."""
        if duration <= 15:
            return "Klip çok kısa — tümü potansiyel hook"
        elif "reaction" in title.lower() or "laugh" in title.lower():
            return "Reaksiyon anı (ilk 3-5 saniye)"
        elif "clutch" in title.lower() or "ace" in title.lower():
            return "Kritik an (son 10 saniye)"
        elif "fail" in title.lower():
            return "Hata anı (ortalar)"
        else:
            return "Başlangıç (ilk 5 saniye)"

    def _suggest_edit(self, duration: float, category: str, edit_pot: float) -> str:
        """TikTok/Instagram Reels-optimized edit önerisi."""
        suggestions = []

        # Platform-optimized crop
        suggestions.append("9:16 vertical crop")

        # Caption style — 85% watch without sound
        if edit_pot >= 60:
            suggestions.append("Animated dynamic captions (Hormozi-style)")
            suggestions.append("Hook text overlay (first 1-3s)")

        # Safe zones for TikTok/Reels UI
        suggestions.append("Safe zone compliance (avoid top 15% + bottom 20%)")

        # Duration-based edits
        if duration > 45:
            suggestions.append("Trim to 21-34s (TikTok sweet spot)")
        elif duration > 34 and category in ("funny", "exciting"):
            suggestions.append("Tighten to 25-30s for max completion rate")

        # No intro/outro rule
        if duration > 10:
            suggestions.append("Remove any intro/outro — kills completion rate")

        # Category-specific
        if category in ("funny", "exciting", "rage"):
            suggestions.append("Fast cuts every 2-3s + zoom effects")
        if category == "skill":
            suggestions.append("Slow-mo on key moment + speed ramp")
        if category == "fail":
            suggestions.append("Freeze frame on fail moment + caption")

        # Stock hook for weak hooks
        if edit_pot < 50:
            suggestions.append("Consider stock video hook at start")

        # DM share trigger (Reels 2026'da #1 sinyal)
        suggestions.append("DM share trigger in last 5s (Reels)")

        return " | ".join(suggestions) if suggestions else "Standard edit"

    def _calculate_platform_scores(self, title: str, duration: float, hook: float, viral: float, engagement: float) -> dict:
        """
        Platform-spesifik skorlar (2026 research).
        TikTok: Raw & Fast aesthetic, 21-34s sweet spot
        Reels: Aesthetic & Curated, DM shares weighted 3-5x
        Shorts: Utility & Search, 15-60s
        X: Conversation starter, 30-90s
        """
        title_lower = title.lower()

        # TikTok: ham, autentik, hızlı — 21-34s optimal
        tiktok_score = (hook * 0.4 + viral * 0.3 + engagement * 0.3)
        if 21 <= duration <= 34:
            tiktok_score += 10
        elif 15 <= duration <= 45:
            tiktok_score += 5
        elif duration > 60:
            tiktok_score -= 8
        # "Raw & Fast" keywords
        if any(w in title_lower for w in ["insane", "crazy", "pog", "clutch", "viral"]):
            tiktok_score += 5
        tiktok_score = min(100, max(0, tiktok_score))

        # Reels: görsel kalite + DM share potential — 15-30s optimal
        reels_score = (hook * 0.3 + viral * 0.25 + engagement * 0.45)
        if 15 <= duration <= 30:
            reels_score += 12
        elif 15 <= duration <= 45:
            reels_score += 6
        elif duration > 60:
            reels_score -= 10
        # "Aesthetic & Curated" keywords
        if any(w in title_lower for w in ["aesthetic", "transformation", "tutorial", "tips"]):
            reels_score += 5
        reels_score = min(100, max(0, reels_score))

        # Shorts: Eğitim/araştırma + izleme süresi — 15-60s optimal
        shorts_score = (hook * 0.3 + viral * 0.3 + engagement * 0.4)
        if 15 <= duration <= 60:
            shorts_score += 10
        elif 15 <= duration <= 45:
            shorts_score += 5
        # "Utility & Search" keywords
        if any(w in title_lower for w in ["how to", "tutorial", "guide", "explained", "tips"]):
            shorts_score += 8
        shorts_score = min(100, max(0, shorts_score))

        # X: Konuşma başlatıcı — 30-90s optimal
        x_score = (hook * 0.25 + viral * 0.4 + engagement * 0.35)
        if 30 <= duration <= 90:
            x_score += 10
        elif 15 <= duration <= 120:
            x_score += 5
        # "Conversation starter" keywords
        if "?" in title or any(w in title_lower for w in ["opinion", "debatable", "controversial", "hot take"]):
            x_score += 10
        x_score = min(100, max(0, x_score))

        return {
            "tiktok_score": round(tiktok_score, 1),
            "reels_score": round(reels_score, 1),
            "shorts_score": round(shorts_score, 1),
            "x_score": round(x_score, 1),
        }

    def _calculate_dm_share_potential(self, title: str, category: str, hook: float) -> int:
        """
        DM share potansiyeli — Reels 2026'da en güçlü sinyal.
        Relatable, "arkadaşını gönder" içeriği, kategoriye göre hesaplanır.
        """
        title_lower = title.lower()
        base = 40

        # Relatable keywords — insanları birini düşünmeye itiyor
        relatable_keywords = {
            "pov", "when ", "you ever", "that feeling when", "me when",
            "tag a", "send this", "reminds me of", "anyone else",
            "we've all been", "that friend", "your bestie", "your brother",
            "tell me you", "without telling me",
        }
        for kw in relatable_keywords:
            if kw in title_lower:
                base += 15
                break

        # Kategoriye göre DM share
        category_dm_bonus = {
            "funny": 15,      # komik içerik paylaşılır
            "rage": 12,       # tartışma yaratır
            "wholesome": 10,  # sevimli içerik paylaşılır
            "fail": 8,        # "ben de yaptım" hissi
            "exciting": 7,
            "skill": 5,
            "educational": 8,
            "other": 0,
        }
        base += category_dm_bonus.get(category, 0)

        # Hook gücünden bonus
        base += int(hook * 0.15)

        return min(100, max(0, base))

    def _generate_send_trigger(self, category: str, title: str) -> str:
        """
        DM share trigger — son 5 saniyede gösterilecek metin (Reels 2026'da #1 sinyal).
        Kategoriye göre en etkili share trigger üretir.
        """
        title_lower = title.lower()

        # Kategoriye göre send trigger'lar
        triggers = {
            "funny": [
                "Buna ihtiyacı olan arkadaşına gönder 🤣",
                "Send this to your funniest friend 😂",
                "Tag someone who would do this",
            ],
            "rage": [
                "Arkadaşına gönder sinirlensin 😤",
                "Send this to someone who needs to see this",
                "Tag a friend who'd rage at this",
            ],
            "wholesome": [
                "Sevdiğin kişiye gönder 💕",
                "Send this to someone you love ❤️",
                "Tag your bestie",
            ],
            "fail": [
                "Bunu arkadaşına gönder, o da yapsın 😅",
                "Send this to your clumsy friend",
                "Tag someone who'd fail like this",
            ],
            "exciting": [
                "Bu anı arkadaşınla paylaş! 🎮",
                "Send this to your gaming squad",
                "Tag your duo partner",
            ],
            "skill": [
                "Bu kadar iyi olan birini etiketle 🎯",
                "Send to someone who thinks they're better 😏",
                "Tag your most skilled friend",
            ],
            "educational": [
                "Bunu öğrenmek isteyen arkadaşına gönder 📚",
                "Send this to someone who needs to know",
                "Tag someone learning this",
            ],
        }

        options = triggers.get(category, triggers["exciting"])
        # Title'a göre custom trigger
        if "bestie" in title_lower or "friend" in title_lower:
            return options[2] if len(options) > 2 else options[0]
        return options[0]

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _score_to_grade(score: float) -> str:
        if score >= 75:
            return "A"
        elif score >= 60:
            return "B"
        elif score >= 40:
            return "C"
        return "D"

    @staticmethod
    def _score_to_verdict(score: float) -> str:
        if score >= 60:
            return "edit"
        elif score >= 40:
            return "watch"
        return "skip"

    @staticmethod
    def _parse_llm_json(text: str) -> Optional[dict]:
        """LLM yanıtından JSON parse et — markdown code fence, trailing comma vb."""
        if not text:
            return None

        import re as _re
        cleaned = text.strip()
        cleaned = _re.sub(r"```(?:json)?\s*", "", cleaned)
        cleaned = _re.sub(r"```\s*$", "", cleaned)

        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            raw = cleaned[start:end]
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
            fixed = raw.replace(",\n}", "\n}").replace(",}", "}")
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _parse_llm_json_array(text: str) -> Optional[list]:
        """LLM yanıtından JSON array parse et — markdown code fence, trailing comma vb."""
        if not text:
            return None

        import re as _re
        cleaned = text.strip()
        cleaned = _re.sub(r"```(?:json)?\s*", "", cleaned)
        cleaned = _re.sub(r"```\s*$", "", cleaned)

        start = cleaned.find("[")
        end = cleaned.rfind("]") + 1
        if start >= 0 and end > start:
            raw = cleaned[start:end]
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
            fixed = raw.replace(",\n]", "\n]").replace(",]", "]")
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass
        return None

    def score_all(self, clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Senkron toplu skorlama (math fallback)."""
        scored = [self._score_with_math(c) for c in clips]
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        return scored

    def get_edit_queue(self, clips: list[dict[str, Any]], min_score: float = 55) -> list[dict[str, Any]]:
        """Edit için uygun klipleri döndür."""
        scored = self.score_all(clips)
        return [c for c in scored if c.get("score", 0) >= min_score]


# Singleton
clip_scorer = ClipScorer()
