"""
Kick API entegrasyon servisi.
- OAuth2 kimlik doğrulama
- Canlı yayın durumu kontrolü
- Kanal bilgileri çekme
- HLS stream URL alma
- Chat mesajlarını izleme
"""
import httpx
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Callable, Awaitable
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class KickAPIService:
    """Kick platform API entegrasyonu."""

    def __init__(self):
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # --- OAuth2 Authentication ---
    async def authenticate(self, code: Optional[str] = None) -> str:
        """OAuth2 token alır (authorization code veya client credentials)."""
        client = await self._get_client()

        if code:
            # Authorization Code Flow
            data = {
                "grant_type": "authorization_code",
                "client_id": settings.kick_client_id,
                "client_secret": settings.kick_client_secret,
                "code": code,
                "redirect_uri": settings.kick_redirect_uri,
            }
        else:
            # Client Credentials Flow
            data = {
                "grant_type": "client_credentials",
                "client_id": settings.kick_client_id,
                "client_secret": settings.kick_client_secret,
            }

        response = await client.post(settings.kick_token_url, data=data)
        response.raise_for_status()
        token_data = response.json()

        self.access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)
        self.token_expires_at = datetime.utcnow() + \
            __import__("datetime").timedelta(seconds=expires_in)

        logger.info("Kick OAuth2 token alındı, expires_in=%d", expires_in)
        return self.access_token

    async def _ensure_token(self):
        """Token geçerli değilse yenile."""
        if not self.access_token or (
            self.token_expires_at and datetime.utcnow() >= self.token_expires_at
        ):
            await self.authenticate()

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    # --- Livestream Bilgileri ---
    async def get_livestream_info(self) -> Dict[str, Any]:
        """
        Kick Public API'den yayıncının canlı yayın bilgisini çeker.
        Endpoint: GET /public/v1/livestreams?broadcaster_user_id=...
        """
        await self._ensure_token()
        client = await self._get_client()

        url = f"{settings.kick_public_api_base}/livestreams"
        params = {"broadcaster_user_id": settings.kick_broadcaster_user_id}

        response = await client.get(
            url, params=params, headers=self._auth_headers()
        )
        response.raise_for_status()
        data = response.json()

        livestreams = data.get("data", [])
        if not livestreams:
            return {"is_live": False}

        ls = livestreams[0]
        return {
            "is_live": ls.get("is_live", False),
            "title": ls.get("title", ""),
            "category": ls.get("category", {}).get("name", ""),
            "viewer_count": ls.get("viewer_count", 0),
            "thumbnail_url": ls.get("thumbnail_url", ""),
            "started_at": ls.get("started_at"),
            "broadcaster_user_id": ls.get("broadcaster_user_id"),
        }

    async def is_live(self) -> bool:
        """Yayıncı şu an canlı mı?"""
        info = await self.get_livestream_info()
        return info.get("is_live", False)

    # --- Stream URL (HLS) ---
    async def get_stream_url(self) -> Optional[str]:
        """
        Kick Web API'den HLS (m3u8) playback URL'sini alır.
        Endpoint: GET /api/v2/channels/{slug}/livestream
        """
        client = await self._get_client()
        slug = settings.kick_channel_slug

        url = f"{settings.kick_api_base}/channels/{slug}/livestream"
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

            playback_url = data.get("playback_url")
            if not playback_url:
                # Alternatif: source içindeki URL
                source = data.get("source", "")
                if source and ".m3u8" in source:
                    playback_url = source

            logger.info("Stream URL alındı: %s", playback_url)
            return playback_url

        except httpx.HTTPError as e:
            logger.error("Stream URL alınamadı: %s", e)
            return None

    # --- Kanal Bilgileri ---
    async def get_channel_info(self) -> Dict[str, Any]:
        """Kanal profil bilgilerini çeker."""
        client = await self._get_client()
        slug = settings.kick_channel_slug

        url = f"{settings.kick_api_base}/channels/{slug}"
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

        return {
            "id": data.get("id"),
            "user_id": data.get("user_id"),
            "slug": data.get("slug"),
            "username": data.get("username"),
            "display_name": data.get("name", data.get("username")),
            "bio": data.get("bio", ""),
            "profile_picture": data.get("profile_pic", ""),
            "follower_count": data.get("followers_count", 0),
            "is_banned": data.get("is_banned", False),
        }

    # --- Chat Mesajları ---
    async def get_chat_messages(self, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Kanal sohbet mesajlarını çeker (polling ile)."""
        await self._ensure_token()
        client = await self._get_client()

        url = f"{settings.kick_api_base}/channels/{settings.kick_channel_slug}/messages"
        params = {}
        if cursor:
            params["cursor"] = cursor

        response = await client.get(
            url, params=params, headers=self._auth_headers()
        )
        response.raise_for_status()
        return response.json()

    async def poll_chat(
        self,
        callback: Callable[[Dict[str, Any]], Awaitable[None]],
        interval: float = 2.0,
    ):
        """Chat mesajlarını periyodik olarak yoklar ve callback'e iletir."""
        cursor = None
        while True:
            try:
                data = await self.get_chat_messages(cursor)
                messages = data.get("data", [])
                cursor = data.get("meta", {}).get("cursor")

                for msg in messages:
                    await callback(msg)

            except Exception as e:
                logger.error("Chat polling hatası: %s", e)

            await asyncio.sleep(interval)

    # --- Webhook Yönetimi ---
    async def subscribe_webhook(self, callback_url: str, events: list) -> bool:
        """Kick webhook abonesi oluşturur."""
        await self._ensure_token()
        client = await self._get_client()

        url = f"{settings.kick_public_api_base}/webhooks"
        payload = {
            "callback_url": callback_url,
            "events": events,
            "broadcaster_user_id": settings.kick_broadcaster_user_id,
        }

        response = await client.post(
            url, json=payload, headers=self._auth_headers()
        )
        return response.status_code == 201

    # --- Periyodik İzleme ---
    async def monitor_stream(
        self,
        on_live: Callable[[Dict[str, Any]], Awaitable[None]],
        on_offline: Callable[[], Awaitable[None]],
        check_interval: float = 30.0,
    ):
        """Yayını periyodik olarak izler, durum değişikliğinde callback çağırır."""
        was_live = False
        while True:
            try:
                info = await self.get_livestream_info()
                is_live = info.get("is_live", False)

                if is_live and not was_live:
                    logger.info("Yayın başladı: %s", info.get("title"))
                    await on_live(info)
                elif not is_live and was_live:
                    logger.info("Yayın bitti.")
                    await on_offline()

                was_live = is_live

            except Exception as e:
                logger.error("Stream izleme hatası: %s", e)

            await asyncio.sleep(check_interval)


# Singleton
kick_service = KickAPIService()
