"""
Kick API entegrasyon servisi - Auth-free (OAuth gerektirmeyen public endpoint'ler).
- Yayin durumu kontrolu (web API)
- Kanal bilgileri
- HLS stream URL
- Chat mesajlari
"""
import httpx
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Callable, Awaitable
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://kick.com/",
}


class KickAPIService:
    """Kick platform API - auth-free web endpoints."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._broadcaster_user_id: Optional[str] = settings.kick_broadcaster_user_id
        self._channel_cache: Dict = {}
        self._cache_time: float = 0
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers=HEADERS,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _ensure_broadcaster_id(self):
        """Broadcaster user ID'si yoksa kanal bilgisinden cek."""
        if self._broadcaster_user_id:
            return
        try:
            info = await self.get_channel_info()
            uid = info.get("user_id") or info.get("id")
            if uid:
                self._broadcaster_user_id = str(uid)
                logger.info("Broadcaster user ID bulundu: %s", self._broadcaster_user_id)
        except Exception as e:
            logger.warning("Broadcaster ID cekilemedi: %s", e)

    # --- Auth (OAuth - opsiyonel) ---
    async def authenticate(self, code: Optional[str] = None) -> str:
        """OAuth2 token alir (opsiyonel, auth-free modda gerekmez)."""
        if not settings.kick_client_id or not settings.kick_client_secret:
            logger.info("OAuth credential yok, auth-free modda calisiliyor")
            return ""

        client = await self._get_client()
        if code:
            data = {
                "grant_type": "authorization_code",
                "client_id": settings.kick_client_id,
                "client_secret": settings.kick_client_secret,
                "code": code,
                "redirect_uri": settings.kick_redirect_uri,
            }
        else:
            data = {
                "grant_type": "client_credentials",
                "client_id": settings.kick_client_id,
                "client_secret": settings.kick_client_secret,
            }

        try:
            response = await client.post(settings.kick_token_url, data=data)
            response.raise_for_status()
            token_data = response.json()
            self.access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            self.token_expires_at = datetime.utcnow() + \
                __import__("datetime").timedelta(seconds=expires_in)
            logger.info("Kick OAuth2 token alindi, expires_in=%d", expires_in)
            return self.access_token
        except Exception as e:
            logger.warning("OAuth hatasi: %s (auth-free modda devam)", e)
            return ""

    def _auth_headers(self) -> Dict[str, str]:
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}

    # --- Kanal Bilgileri (auth-free web API) ---
    async def get_channel_info(self) -> Dict[str, Any]:
        """Kanal profil bilgilerini ceker (auth-free)."""
        client = await self._get_client()
        slug = settings.kick_channel_slug

        url = f"{settings.kick_api_base}/channels/{slug}"
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

            result = {
                "id": data.get("id"),
                "user_id": data.get("user_id"),
                "slug": data.get("slug"),
                "username": data.get("username"),
                "display_name": data.get("name") or data.get("username"),
                "bio": data.get("bio", ""),
                "profile_picture": data.get("profile_pic", ""),
                "follower_count": data.get("followers_count", 0),
                "is_banned": data.get("is_banned", False),
            }

            self._channel_cache = result
            self._cache_time = datetime.utcnow().timestamp()

            return result
        except httpx.HTTPError as e:
            logger.error("Kanal bilgisi alinamadi: %s", e)
            return self._channel_cache or {}

    # --- Yayin Durumu (auth-free) ---
    async def get_livestream_info(self) -> Dict[str, Any]:
        """
        Yayincinin canli yayin bilgisini ceker.
        Web API: GET /api/v2/channels/{slug}/livestream
        Auth gerektirmez.
        """
        client = await self._get_client()
        slug = settings.kick_channel_slug

        url = f"{settings.kick_api_base}/channels/{slug}/livestream"
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

            # livestream None ise yayin yok
            livestream = data.get("livestream")
            if livestream is None or livestream is False or livestream == {}:
                return {"is_live": False, "title": "", "slug": slug}

            # is_live kontrolu
            is_live = data.get("is_live", False)
            if not is_live and livestream:
                # livestream objesi varsa yayin var demektir
                is_live = True

            title = ""
            category = ""
            viewer_count = 0
            thumbnail_url = ""
            started_at = None
            playback_url = None

            if isinstance(livestream, dict):
                title = livestream.get("title", "")
                category = livestream.get("categories", [{}])
                if isinstance(category, list) and category:
                    category = category[0].get("name", "") if isinstance(category[0], dict) else str(category[0])
                elif not isinstance(category, str):
                    category = ""
                viewer_count = livestream.get("viewer_count", 0)
                thumbnail_url = livestream.get("thumbnail", {}).get("url", "") if isinstance(livestream.get("thumbnail"), dict) else livestream.get("thumbnail_url", "")
                started_at = livestream.get("created_at") or livestream.get("started_at")
                playback_url = livestream.get("playback_url", "")

            return {
                "is_live": is_live,
                "title": title,
                "category": category,
                "viewer_count": viewer_count,
                "thumbnail_url": thumbnail_url,
                "started_at": started_at,
                "playback_url": playback_url,
                "slug": slug,
            }

        except httpx.HTTPError as e:
            logger.error("Yayin durumu alinamadi: %s", e)
            return {"is_live": False, "title": "", "slug": slug}

    async def is_live(self) -> bool:
        """Yayinci su an canli mi?"""
        info = await self.get_livestream_info()
        return info.get("is_live", False)

    # --- Stream URL (HLS) ---
    async def get_stream_url(self) -> Optional[str]:
        """HLS (m3u8) playback URL'sini alir."""
        client = await self._get_client()
        slug = settings.kick_channel_slug

        url = f"{settings.kick_api_base}/channels/{slug}/livestream"
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

            # playback_url dogrudan ust seviyede
            playback_url = data.get("playback_url")
            if playback_url:
                return playback_url

            # livestream icinde
            livestream = data.get("livestream")
            if isinstance(livestream, dict):
                playback_url = livestream.get("playback_url")
                if playback_url:
                    return playback_url

            # source icinde
            source = data.get("source", "")
            if source and ".m3u8" in source:
                return source

            logger.warning("Stream URL bulunamadi")
            return None

        except httpx.HTTPError as e:
            logger.error("Stream URL alinamadi: %s", e)
            return None

    # --- Chat Mesajlari ---
    async def get_chat_messages(self, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Kanal sohbet mesajlarini ceker."""
        client = await self._get_client()
        slug = settings.kick_channel_slug

        url = f"{settings.kick_api_base}/channels/{slug}/messages"
        params = {}
        if cursor:
            params["cursor"] = cursor

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error("Chat mesaji alinamadi: %s", e)
            return {"data": []}

    async def poll_chat(
        self,
        callback: Callable[[Dict[str, Any]], Awaitable[None]],
        interval: float = 2.0,
    ):
        """Chat mesajlarini periyodik olarak yoklar."""
        cursor = None
        while True:
            try:
                data = await self.get_chat_messages(cursor)
                messages = data.get("data", [])
                cursor = data.get("meta", {}).get("cursor")

                for msg in messages:
                    await callback(msg)
            except Exception as e:
                logger.error("Chat polling hatasi: %s", e)
            await asyncio.sleep(interval)

    # --- Periyodik Izleme ---
    async def monitor_stream(
        self,
        on_live: Callable[[Dict[str, Any]], Awaitable[None]],
        on_offline: Callable[[], Awaitable[None]],
        check_interval: float = 30.0,
    ):
        """Yayini periyodik olarak izler."""
        was_live = False
        while True:
            try:
                info = await self.get_livestream_info()
                is_live = info.get("is_live", False)

                if is_live and not was_live:
                    logger.info("YAYIN BASLADI: %s", info.get("title"))
                    await on_live(info)
                elif not is_live and was_live:
                    logger.info("YAYIN BITTI.")
                    await on_offline()

                was_live = is_live
            except Exception as e:
                logger.error("Stream izleme hatasi: %s", e)
            await asyncio.sleep(check_interval)


# Singleton
kick_service = KickAPIService()
