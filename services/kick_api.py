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
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Awaitable
from config import get_settings

try:
    from curl_cffi.requests import Session as CurlSession
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    _CURL_CFFI_AVAILABLE = False

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

    # --- Public VOD archive ---
    @staticmethod
    def _extract_vod_items(payload: Any) -> list[dict[str, Any]]:
        """Accept the public API response shapes used by Kick video listings."""
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []

        candidates = payload.get("data") or payload.get("videos") or payload.get("results")
        if isinstance(candidates, dict):
            candidates = (
                candidates.get("data")
                or candidates.get("videos")
                or candidates.get("results")
            )
        if not isinstance(candidates, list):
            return []
        return [item for item in candidates if isinstance(item, dict)]

    @staticmethod
    def _category_name(raw: Any) -> str:
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            return str(raw.get("name") or raw.get("slug") or "")
        if isinstance(raw, list) and raw:
            return KickAPIService._category_name(raw[0])
        return ""

    def _normalize_public_vod(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize a public VOD payload without trusting cross-channel data."""
        channel = raw.get("channel") if isinstance(raw.get("channel"), dict) else {}
        livestream = raw.get("livestream") if isinstance(raw.get("livestream"), dict) else {}
        item_slug = str(channel.get("slug") or raw.get("channel_slug") or "").lower()
        if item_slug and item_slug != settings.kick_channel_slug:
            logger.warning("Ignoring VOD from unexpected channel: %s", item_slug)
            return None

        vod_id = raw.get("id") or raw.get("uuid") or raw.get("slug")
        if vod_id is None:
            return None
        vod_id = str(vod_id)

        url = (
            raw.get("url")
            or raw.get("share_url")
            or raw.get("video_url")
            or raw.get("canonical_url")
        )
        if not isinstance(url, str) or not url.startswith("https://kick.com/"):
            url = f"https://kick.com/{settings.kick_channel_slug}/videos/{vod_id}"

        return {
            "vod_id": vod_id,
            "url": url,
            "title": str(raw.get("title") or livestream.get("title") or "Untitled VOD"),
            "created_at": raw.get("created_at") or raw.get("published_at") or "",
            "duration": raw.get("duration") or livestream.get("duration") or 0,
            "thumbnail_url": raw.get("thumbnail") or raw.get("thumbnail_url") or "",
            "category": self._category_name(
                raw.get("categories") or raw.get("category") or livestream.get("categories")
            ),
        }

    async def _list_public_vods_curl_cffi(self, limit: int) -> list[dict[str, Any]]:
        """curl_cffi ile Cloudflare bypass ederek VOD listesi çek."""
        if not _CURL_CFFI_AVAILABLE:
            logger.info("curl_cffi not installed, skipping")
            return []

        slug = settings.kick_channel_slug
        url = f"https://kick.com/api/v2/channels/{slug}/videos"
        try:
            def _fetch():
                session = CurlSession(impersonate="chrome124")
                resp = session.get(url, params={"limit": limit, "sort": "date"}, timeout=15)
                resp.raise_for_status()
                return resp.json()

            data = await asyncio.to_thread(_fetch)
        except Exception as exc:
            logger.info("curl_cffi VOD list failed: %s", exc)
            return []

        items = data if isinstance(data, list) else data if isinstance(data, dict) else []
        if isinstance(data, dict):
            items = data.get("data") or data.get("videos") or data.get("results") or []

        vods: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            vod_id = str(raw.get("id") or raw.get("slug") or "")
            if not vod_id:
                continue
            title = raw.get("session_title") or raw.get("title") or "Untitled VOD"
            thumb = raw.get("thumbnail") or {}
            if isinstance(thumb, dict):
                thumbnail_url = thumb.get("src") or ""
            else:
                thumbnail_url = str(thumb)
            created_at = raw.get("created_at") or raw.get("start_time") or ""
            duration_raw = raw.get("duration") or 0
            duration = duration_raw / 1000 if duration_raw > 100000 else duration_raw
            vod_slug = raw.get("slug") or vod_id
            web_url = f"https://kick.com/{slug}/videos/{vod_slug}"

            vods.append({
                "vod_id": vod_id,
                "url": web_url,
                "title": title,
                "created_at": str(created_at),
                "duration": duration,
                "thumbnail_url": thumbnail_url,
                "category": "Kick",
            })
        logger.info("curl_cffi discovered %d VODs", len(vods))
        return vods[:limit]

    async def list_public_vods(self, limit: int = 10) -> list[dict[str, Any]]:
        """List public VODs for the configured, fixed Kick channel.

        Öncelik sırası: curl_cffi (Cloudflare bypass) > httpx (eski API) > yt-dlp.
        """
        limit = max(1, min(int(limit), 50))

        # Strateji 1: curl_cffi ile Cloudflare bypass
        vods = await self._list_public_vods_curl_cffi(limit)
        if vods:
            return vods

        # Strateji 2: httpx ile doğrudan Kick API (eski, 403 alabilir)
        client = await self._get_client()
        url = f"{settings.kick_api_base}/channels/{settings.kick_channel_slug}/videos"
        try:
            response = await client.get(url, params={"limit": limit, "sort": "date"})
            response.raise_for_status()
            vods = []
            for raw in self._extract_vod_items(response.json()):
                vod = self._normalize_public_vod(raw)
                if vod is not None:
                    vods.append(vod)
            if vods:
                return vods[:limit]
        except httpx.HTTPError:
            pass

        # Strateji 3: yt-dlp fallback
        return await self._try_ytdlp(
            f"https://kick.com/{settings.kick_channel_slug}", limit, cookie_args=[]
        )

    # --- Yayin Durumu (auth-free, curl_cffi Cloudflare bypass) ---
    async def get_livestream_info(self) -> Dict[str, Any]:
        """
        Yayincinin canli yayin bilgisini ceker.
        Once curl_cffi (Cloudflare bypass), sonra httpx dener.
        """
        slug = settings.kick_channel_slug
        url = f"{settings.kick_api_base}/channels/{slug}/livestream"
        data = None

        # Strateji 1: curl_cffi ile Cloudflare bypass
        if _CURL_CFFI_AVAILABLE:
            try:
                def _fetch():
                    session = CurlSession(impersonate="chrome124")
                    resp = session.get(url, timeout=15)
                    resp.raise_for_status()
                    return resp.json()
                data = await asyncio.to_thread(_fetch)
            except Exception as e:
                logger.debug("curl_cffi livestream failed: %s", e)

        # Strateji 2: httpx fallback
        if data is None:
            try:
                client = await self._get_client()
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                logger.debug("httpx livestream failed: %s", e)
                return {"is_live": False, "title": "", "slug": slug}

        # Yaniti isle
        livestream = data.get("livestream")
        if livestream is None or livestream is False or livestream == {}:
            return {"is_live": False, "title": "", "slug": slug}

        is_live = data.get("is_live", False)
        if not is_live and livestream:
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

    # --- Public Clips (curl_cffi Cloudflare bypass) ---
    async def list_channel_clips(
        self,
        limit: int = 25,
        sort: str = "newest",
    ) -> list[dict[str, Any]]:
        """Kanal public clip'lerini listele. Once curl_cffi, sonra httpx dener."""
        slug = settings.kick_channel_slug
        url = f"{settings.kick_api_base}/channels/{slug}/clips"
        params = {"limit": limit, "sort": sort}

        # Strateji 1: curl_cffi ile Cloudflare bypass
        if _CURL_CFFI_AVAILABLE:
            try:
                def _fetch():
                    session = CurlSession(impersonate="chrome124")
                    resp = session.get(url, params=params, timeout=15)
                    resp.raise_for_status()
                    return resp.json()
                data = await asyncio.to_thread(_fetch)
                clips = []
                items = data if isinstance(data, list) else data.get("data", data.get("clips", []))
                if isinstance(items, list):
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        clip = self._normalize_clip(item)
                        if clip:
                            clips.append(clip)
                if clips:
                    logger.info("curl_cffi discovered %d clips for %s", len(clips), slug)
                    return clips[:limit]
            except Exception as e:
                logger.debug("curl_cffi clips failed: %s", e)

        # Strateji 2: httpx fallback
        try:
            client = await self._get_client()
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            clips = []
            items = data if isinstance(data, list) else data.get("data", data.get("clips", []))
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    clip = self._normalize_clip(item)
                    if clip:
                        clips.append(clip)
            logger.info("Discovered %d public clips for %s", len(clips), slug)
            return clips[:limit]
        except Exception as e:
            logger.debug("Clips listesi alinamadi: %s", e)
            return []

    async def list_clips(
        self,
        limit: int = 25,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """Tum public clip'leri listele (kick.com/api/v2/clips).

        Farkli kanallardan da clip gelebilir, sadece thetuncay filtrelenir.
        """
        client = await self._get_client()

        url = f"{settings.kick_api_base}/clips"
        params = {"limit": min(limit, 50), "page": max(page, 1)}

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            clips = []
            items = data if isinstance(data, list) else data.get("data", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                clip = self._normalize_clip(item)
                if clip and clip.get("channel_slug") == settings.kick_channel_slug:
                    clips.append(clip)

            return clips[:limit]

        except httpx.HTTPError as e:
            logger.error("Global clips listesi alinamadi: %s", e)
            return []

    async def get_clip_details(self, clip_id: str) -> Optional[Dict[str, Any]]:
        """Tek bir clip'in detayini cek.

        Endpoint: GET /api/v2/clips/{clip_id}
        """
        client = await self._get_client()
        url = f"{settings.kick_api_base}/clips/{clip_id}"

        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            return self._normalize_clip(data)
        except httpx.HTTPError as e:
            logger.error("Clip detayi alinamadi: %s", e)
            return None

    def _normalize_clip(self, raw: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Clip payload'unu normalize et."""
        clip_id = raw.get("id") or raw.get("clip_id") or raw.get("uuid")
        if not clip_id:
            return None

        # Kanal bilgisi
        channel = raw.get("channel", {})
        if isinstance(channel, dict):
            channel_slug = channel.get("slug", "")
        else:
            channel_slug = raw.get("channel_slug", "")

        # Sadece hedef kanalin clip'leri
        if channel_slug and channel_slug != settings.kick_channel_slug:
            return None

        # Clip URL
        clip_url = (
            raw.get("clip_url")
            or raw.get("url")
            or raw.get("share_url")
            or raw.get("video_url")
            or f"https://kick.com/{channel_slug}/clip/{clip_id}"
        )

        # Süre (saniye)
        duration = raw.get("duration", 0)
        if duration > 1000:
            duration = duration / 1000

        # Kullanıcı bilgisi
        creator = raw.get("creator", raw.get("user", {}))
        creator_name = ""
        creator_id = ""
        if isinstance(creator, dict):
            creator_name = creator.get("username", creator.get("display_name", ""))
            creator_id = str(creator.get("id", ""))

        return {
            "clip_id": str(clip_id),
            "channel_slug": channel_slug,
            "channel_url": f"https://kick.com/{channel_slug}",
            "clip_url": clip_url,
            "title": raw.get("title", raw.get("session_title", "")),
            "creator_username": creator_name,
            "creator_id": creator_id,
            "created_at": raw.get("created_at", raw.get("created", "")),
            "duration": duration,
            "views": raw.get("views", raw.get("view_count", 0)),
            "likes": raw.get("likes", raw.get("like_count", 0)),
            "thumbnail_url": raw.get("thumbnail", raw.get("thumbnail_url", "")),
            "language": raw.get("language", ""),
            "category": raw.get("category", ""),
        }

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
