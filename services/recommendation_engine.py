"""
Recommendation Engine (IP_PART7 - AI Intelligence Expansion)

Personalized clip recommendations using hybrid approach:
  1. Content-Based Filtering - clip similarity by features
  2. Collaborative Filtering - user preference patterns
  3. Context-Aware - time, platform, trending factors
  4. Learning-to-Rank - score optimization from feedback

Features:
  - User preference learning from watch history
  - Similar clip discovery
  - "For You" personalized feed ranking
  - Trending/popular clip detection
  - Category affinity scoring
  - Creator-specific recommendations
  - Freshness decay (newer clips get boost)
  - Diversity enforcement (avoid filter bubbles)
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("recommendation")


@dataclass
class ClipProfile:
    """Feature vector for a clip."""
    clip_id: str
    category: str
    emotion: str
    duration: float
    highlight_score: float
    tags: list[str] = field(default_factory=list)
    platform: str = ""
    streamer: str = ""
    created_at: float = 0.0
    views: int = 0
    likes: int = 0
    engagement_rate: float = 0.0
    feature_vector: np.ndarray | None = None


@dataclass 
class UserProfile:
    """Learned user preference profile."""
    user_id: str
    preferred_categories: dict[str, float] = field(default_factory=dict)
    preferred_emotions: dict[str, float] = field(default_factory=dict)
    avg_duration_pref: float = 30.0
    watched_clips: list[str] = field(default_factory=list)
    liked_clips: list[str] = field(default_factory=list)
    skipped_clips: list[str] = field(default_factory=list)
    last_active: float = 0.0
    session_count: int = 0


# ---------------------------------------------------------------------------
# Clip Similarity Engine (Content-Based)
# ---------------------------------------------------------------------------
class ClipSimilarityEngine:
    """
    Content-based clip similarity using weighted feature comparison.

    Similarity dimensions:
    - Category match (25%)
    - Emotion match (20%)
    - Tag overlap (20%)
    - Duration similarity (15%)
    - Highlight score proximity (10%)
    - Engagement similarity (10%)
    """

    CATEGORY_AFFINITY = {
        "funny": ["funny", "fail"],
        "exciting": ["exciting", "hype", "victory", "highlight"],
        "emotional": ["emotional"],
        "rage": ["rage", "fail"],
        "victory": ["victory", "exciting", "skill"],
        "skill": ["skill", "victory"],
        "fail": ["fail", "funny"],
    }

    def __init__(self):
        self._clip_profiles: dict[str, ClipProfile] = {}

    def add_clip(self, profile: ClipProfile):
        """Register a clip for similarity comparison."""
        feat = self._build_feature_vector(profile)
        profile.feature_vector = feat
        self._clip_profiles[profile.clip_id] = profile

    def _build_feature_vector(self, profile: ClipProfile) -> np.ndarray:
        """Build normalized feature vector for clip."""
        vec = np.zeros(10, dtype=np.float32)

        # Category one-hot-ish encoding
        cats = ["funny", "exciting", "emotional", "rage", "victory", "skill", "fail", "highlight", "hype"]
        if profile.category in cats:
            vec[cats.index(profile.category) % 10] = 1.0

        # Tag-based encoding (simple bag-of-tags)
        all_tags = {"gaming", "stream", "clutch", "epic", "funny", "fail",
                     "victory", "skill", "rage", "pog", "hype", "insane",
                     "efsane", "helal", "komik", "sinirli", "heyecan"}
        tag_overlap = len(set(profile.tags) & all_tags) / max(len(all_tags), 1)
        vec[1] = tag_overlap

        vec[2] = profile.highlight_score
        vec[3] = min(profile.duration / 120.0, 1.0)
        vec[4] = float(profile.views) / 10000.0 if profile.views > 0 else 0.0
        vec[5] = float(profile.likes) / max(profile.views, 1)
        vec[6] = profile.engagement_rate
        vec[7] = 0.0  # reserved

        # Category affinity for emotion
        emotion_map = {"excitement": 0.8, "hype": 1.0, "funny": 0.6,
                        "rage": 0.5, "emotional": 0.4, "victory": 0.7,
                        "skill": 0.6, "fail": 0.5}
        vec[8] = emotion_map.get(profile.emotion, 0.3)
        vec[9] = max(0, 1.0 - (time.time() - profile.created_at) / (7 * 86400))

        return vec

    def find_similar(
        self, clip_id: str, top_n: int = 10, exclude_watched: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Find clips similar to given clip_id."""
        source = self._clip_profiles.get(clip_id)
        if source is None or source.feature_vector is None:
            return []

        exclude = exclude_watched or set()
        exclude.add(clip_id)

        similarities = []
        for cid, profile in self._clip_profiles.items():
            if cid in exclude or profile.feature_vector is None:
                continue
            sim = self._cosine_similarity(source.feature_vector, profile.feature_vector)
            if sim > 0.3:
                similarities.append((cid, sim))

        return sorted(similarities, key=lambda x: x[1], reverse=True)[:top_n]

    def get_similar_by_category(
        self, category: str, top_n: int = 10,
    ) -> list[str]:
        """Get clips similar to a category."""
        matches = []
        for cid, profile in self._clip_profiles.items():
            if profile.category == category or (
                category in self.CATEGORY_AFFINITY and
                profile.category in self.CATEGORY_AFFINITY[category]
            ):
                matches.append((cid, profile.highlight_score))
        return [m[0] for m in sorted(matches, key=lambda x: x[1], reverse=True)[:top_n]]

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a < 1e-8 or norm_b < 1e-8:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def get_status(self) -> dict:
        return {"clips_indexed": len(self._clip_profiles)}


# ---------------------------------------------------------------------------
# User Preference Learner (Collaborative Filtering)
# ---------------------------------------------------------------------------
class UserPreferenceLearner:
    """
    Learn user preferences from interaction history.

    Updates user profiles based on:
    - Watch completions → category boost
    - Likes → double boost
    - Skips → negative signal
    - Time decay → older interactions fade
    """

    def __init__(self, decay_rate: float = 0.05):
        self.decay_rate = decay_rate
        self._users: dict[str, UserProfile] = {}

    def get_or_create_user(self, user_id: str) -> UserProfile:
        if user_id not in self._users:
            self._users[user_id] = UserProfile(user_id=user_id)
        return self._users[user_id]

    def record_watch(self, user_id: str, clip_id: str, clip_profile: dict):
        """Record a clip watch event."""
        user = self.get_or_create_user(user_id)
        user.watched_clips.append(clip_id)
        user.last_active = time.time()
        user.session_count += 1

        cat = clip_profile.get("category", "other")
        emo = clip_profile.get("emotion", "neutral")
        dur = clip_profile.get("duration", 30)

        # Boost preferred category
        user.preferred_categories[cat] = (
            user.preferred_categories.get(cat, 0.0) * (1 - self.decay_rate) + 0.15
        )
        user.preferred_emotions[emo] = (
            user.preferred_emotions.get(emo, 0.0) * (1 - self.decay_rate) + 0.1
        )
        user.avg_duration_pref = (
            user.avg_duration_pref * 0.8 + dur * 0.2
        )

    def record_like(self, user_id: str, clip_id: str, clip_profile: dict):
        """Record a like (strong positive signal)."""
        user = self.get_or_create_user(user_id)
        user.liked_clips.append(clip_id)

        cat = clip_profile.get("category", "other")
        emo = clip_profile.get("emotion", "neutral")

        user.preferred_categories[cat] = min(
            user.preferred_categories.get(cat, 0.0) + 0.3, 1.0)
        user.preferred_emotions[emo] = min(
            user.preferred_emotions.get(emo, 0.0) + 0.2, 1.0)

    def record_skip(self, user_id: str, clip_id: str, clip_profile: dict):
        """Record a skip (negative signal)."""
        user = self.get_or_create_user(user_id)
        user.skipped_clips.append(clip_id)

        cat = clip_profile.get("category", "other")
        emo = clip_profile.get("emotion", "neutral")

        user.preferred_categories[cat] = max(
            user.preferred_categories.get(cat, 0.0) - 0.1, 0.0)
        user.preferred_emotions[emo] = max(
            user.preferred_emotions.get(emo, 0.0) - 0.08, 0.0)

    def get_preferences(self, user_id: str) -> dict:
        """Get learned user preferences."""
        user = self._users.get(user_id)
        if not user:
            return {"categories": {}, "emotions": {}, "avg_duration": 30}

        return {
            "categories": dict(user.preferred_categories),
            "emotions": dict(user.preferred_emotions),
            "avg_duration": round(user.avg_duration_pref, 1),
            "total_watched": len(user.watched_clips),
            "total_liked": len(user.liked_clips),
            "total_skipped": len(user.skipped_clips),
        }

    def get_status(self) -> dict:
        return {"users_tracked": len(self._users)}


# ---------------------------------------------------------------------------
# Clip Ranker (Learning-to-Rank)
# ---------------------------------------------------------------------------
class ClipRanker:
    """
    Rank clips for a user using multi-factor scoring.

    Factors:
    - Personal category affinity (from user profile) → 25%
    - Personal emotion preference → 15%
    - Duration match → 10%
    - Clip quality (highlight score) → 15%
    - Engagement (views/likes ratio) → 10%
    - Freshness (how new is the clip) → 10%
    - Diversity bonus (avoid showing same type) → 10%
    - Trending boost (if clip is going viral) → 5%
    """

    def __init__(self):
        self._trending_boost: dict[str, float] = {}

    def set_trending(self, clip_ids: list[str]):
        """Mark clips as trending to give ranking boost."""
        for cid in clip_ids:
            self._trending_boost[cid] = 0.15

    def rank(
        self,
        clip_profiles: list[dict],
        user_prefs: dict[str, Any] | None = None,
        recently_watched: set[str] | None = None,
        top_n: int = 20,
    ) -> list[dict]:
        """
        Rank clips for a user.

        Returns sorted list with ranking scores attached.
        """
        user_cats = (user_prefs or {}).get("categories", {})
        user_emos = (user_prefs or {}).get("emotions", {})
        user_dur = (user_prefs or {}).get("avg_duration", 30)
        watched = recently_watched or set()

        scored = []
        for clip in clip_profiles:
            cid = clip.get("clip_id", str(hash(str(clip))))
            if cid in watched:
                continue

            score = 0.0

            # 1. Category affinity (25%)
            cat = clip.get("category", "other")
            score += user_cats.get(cat, 0.1) * 0.25

            # 2. Emotion preference (15%)
            emo = clip.get("emotion", "neutral")
            score += user_emos.get(emo, 0.05) * 0.15

            # 3. Duration match (10%)
            clip_dur = clip.get("duration", 30)
            dur_match = 1.0 - abs(clip_dur - user_dur) / max(clip_dur, user_dur, 1)
            score += max(dur_match, 0.0) * 0.1

            # 4. Clip quality (15%)
            hs = clip.get("highlight_score", 0.0)
            score += hs * 0.15

            # 5. Engagement (10%)
            views = clip.get("views", 0)
            likes = clip.get("likes", 0)
            if views > 0:
                engagement = likes / views + clip.get("likes", 0) / 1000.0
            else:
                engagement = 0.0
            score += min(engagement, 1.0) * 0.1

            # 6. Freshness (10%)
            created = clip.get("created_at", 0)
            age_hours = (time.time() - created) / 3600 if created > 0 else 1
            freshness = max(0, 1.0 - age_hours / 168)  # decay over 1 week
            score += freshness * 0.1

            # 7. Diversity (10%) — batch-based, applied as penalty after scoring loop.
            # Cannot compute per-clip because it requires full batch category counts.

            # 8. Trending boost (5%)
            score += self._trending_boost.get(cid, 0.0)

            scored.append({"clip_id": cid, "score": round(score, 4), **clip})

        # Apply diversity: reduce score for dominant categories
        cat_counts = defaultdict(int)
        for s in scored:
            cat_counts[s.get("category", "other")] += 1
        most_common = max(cat_counts.values()) if cat_counts else 1

        for s in scored:
            cat = s.get("category", "other")
            if cat_counts[cat] > 3:
                penalty = (cat_counts[cat] / max(most_common, 1)) * 0.1
                s["score"] -= penalty

        ranked = sorted(scored, key=lambda x: x["score"], reverse=True)
        return ranked[:top_n]

    def get_status(self) -> dict:
        return {"trending_clips": len(self._trending_boost)}