"""
Social Media Poster — Postiz Self-Hosted Entegrasyonu
──────────────────────────────────────────────────────
Zero-cost: Postiz AGPL-3.0, self-hosted, bedava OAuth.
Platform desteği: TikTok, YouTube, Instagram, Twitter/X, LinkedIn, Reddit, Facebook, Bluesky, Mastodon + 20+

Postiz kurulumu (opsiyonel):
  docker compose -f docker-compose.postiz.yml up -d
  Veya mevcut Postiz instance'ına bağlan.

API docs: /public/v1/posts, /public/v1/integrations, /public/v1/upload
CLI: npm install -g postiz → postiz auth:login, postiz posts:create

Zero-cost kuralı: Tüm platform OAuth key'leri bedava.
Paid API key gerektirmez (OpenAI key sadece AI features için, opsiyonel).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger("social_poster")


@dataclass
class PostizConfig:
    """Postiz instance yapılandırması."""
    base_url: str = "http://localhost:5000"
    api_key: str = ""  # Postiz API key (opsiyonel, auth server varsa)
    timeout: float = 30.0
    max_retries: int = 2


@dataclass
class PostizIntegration:
    """Postiz'deki bir platform entegrasyonu (OAuth bağlanmış)."""
    id: str
    name: str
    platform: str  # "tiktok", "youtube", "instagram", "twitter", etc.
    username: str = ""
    active: bool = True


@dataclass
class ScheduledPost:
    """Zamanlanmış gönderi."""
    id: str
    content: str
    integration_ids: list[str]
    scheduled_at: float  # unix timestamp
    status: str = "pending"  # pending, published, failed
    media_urls: list[str] = field(default_factory=list)


class SocialPoster:
    """
    Postiz REST API wrapper.

    Kullanım:
        poster = SocialPoster(PostizConfig(base_url="http://localhost:5000"))
        await poster.initialize()

        integrations = await poster.list_integrations()
        result = await poster.create_post(
            content="Efsane clutch! #gaming",
            integration_ids=[integrations[0].id],
            scheduled_at=time.time() + 3600,
        )
    """

    def __init__(self, config: Optional[PostizConfig] = None):
        self.config = config or PostizConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._initialized = False
        self._integrations: list[PostizIntegration] = []

    async def initialize(self) -> bool:
        """Postiz'e bağlan ve integrasyonları keşfet."""
        try:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                headers=self._build_headers(),
            )
            # Health check
            resp = await self._client.get("/api/health")
            if resp.status_code == 200:
                self._initialized = True
                self._integrations = await self._fetch_integrations()
                logger.info(
                    "Postiz connected: %d integrations found",
                    len(self._integrations),
                )
                return True
            logger.warning("Postiz health check failed: %s", resp.status_code)
        except Exception as e:
            logger.warning("Postiz unavailable: %s", e)
        return False

    async def close(self):
        if self._client:
            await self._client.aclose()

    # ── Integrations ──────────────────────────────────────────────────

    async def list_integrations(self) -> list[PostizIntegration]:
        """Bağlı platform integrasyonlarını listele."""
        if not self._initialized:
            return []
        return list(self._integrations)

    async def get_integration(self, platform: str) -> Optional[PostizIntegration]:
        """Belirli bir platform için ilk integrasyonu bul."""
        for integ in self._integrations:
            if integ.platform.lower() == platform.lower() and integ.active:
                return integ
        return None

    # ── Posts ─────────────────────────────────────────────────────────

    async def create_post(
        self,
        content: str,
        integration_ids: list[str],
        scheduled_at: Optional[float] = None,
        media_urls: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
    ) -> Optional[ScheduledPost]:
        """
        Postiz üzerinden gönderi oluştur veya zamanla.

        Args:
            content: Gönderi metni
            integration_ids: Postiz integration ID'leri (hangi platformlara posting yapılacak)
            scheduled_at: Unix timestamp (None = hemen yayımla)
            media_urls: Medya URL'leri (video, resim)
            tags: Hashtag'ler
        """
        if not self._initialized:
            logger.warning("Postiz not initialized")
            return None

        post_data = {
            "content": content,
            "integrations": integration_ids,
            "type": "now" if scheduled_at is None else "schedule",
        }
        if scheduled_at:
            post_data["date"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(scheduled_at)
            )
        if media_urls:
            post_data["media"] = [{"url": url} for url in media_urls]

        try:
            resp = await self._client.post("/public/v1/posts", json=post_data)
            if resp.status_code in (200, 201):
                data = resp.json()
                return ScheduledPost(
                    id=data.get("id", ""),
                    content=content,
                    integration_ids=integration_ids,
                    scheduled_at=scheduled_at or time.time(),
                    status="scheduled" if scheduled_at else "published",
                    media_urls=media_urls or [],
                )
            logger.error("Postiz post failed: %s %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("Postiz post error: %s", e)
        return None

    async def post_now(
        self,
        content: str,
        platform: str,
        media_url: Optional[str] = None,
    ) -> Optional[ScheduledPost]:
        """
        Tek platforma hemen posting yap (yardımcı method).

        Args:
            content: Gönderi metni
            platform: "tiktok", "youtube", "instagram", "twitter", etc.
            media_url: Tek medya URL'i (opsiyonel)
        """
        integ = await self.get_integration(platform)
        if not integ:
            logger.warning("No active integration for platform: %s", platform)
            return None

        media = [media_url] if media_url else None
        return await self.create_post(
            content=content,
            integration_ids=[integ.id],
            media_urls=media,
        )

    async def post_cross_platform(
        self,
        content: str,
        platforms: list[str],
        media_url: Optional[str] = None,
    ) -> dict[str, Optional[ScheduledPost]]:
        """
        Çoklu platforma aynı anda posting.

        Returns:
            {platform: ScheduledPost veya None}
        """
        results: dict[str, Optional[ScheduledPost]] = {}
        for platform in platforms:
            results[platform] = await self.post_now(
                content=content,
                platform=platform,
                media_url=media_url,
            )
        return results

    # ── Media Upload ──────────────────────────────────────────────────

    async def upload_media(
        self,
        file_path: str,
        integration_id: str,
    ) -> Optional[str]:
        """Postiz'e medya yükle ve URL dön."""
        if not self._initialized:
            return None
        try:
            with open(file_path, "rb") as f:
                resp = await self._client.post(
                    "/public/v1/upload",
                    files={"file": f},
                    data={"integration": integration_id},
                )
            if resp.status_code in (200, 201):
                data = resp.json()
                return data.get("url") or data.get("id")
            logger.error("Postiz upload failed: %s", resp.status_code)
        except Exception as e:
            logger.error("Postiz upload error: %s", e)
        return None

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Poster durumu."""
        return {
            "initialized": self._initialized,
            "base_url": self.config.base_url,
            "integrations_count": len(self._integrations),
            "platforms": [
                {"id": i.id, "platform": i.platform, "username": i.username, "active": i.active}
                for i in self._integrations
            ],
        }

    # ── Internal ──────────────────────────────────────────────────────

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    async def _fetch_integrations(self) -> list[PostizIntegration]:
        """Postiz'den bağlı integrasyonları çek."""
        try:
            resp = await self._client.get("/public/v1/integrations")
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("integrations", [])
                return [
                    PostizIntegration(
                        id=str(item.get("id", "")),
                        name=item.get("name", ""),
                        platform=item.get("type", item.get("platform", "unknown")),
                        username=item.get("username", ""),
                        active=item.get("active", True),
                    )
                    for item in items
                ]
        except Exception as e:
            logger.warning("Failed to fetch integrations: %s", e)
        return []


# Singleton
social_poster = SocialPoster()
