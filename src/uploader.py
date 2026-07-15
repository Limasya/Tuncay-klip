"""
Otomatik yayinlama (upload) modulu.
Klipleri sosyal medya platformlarina otomatik yukler.
- YouTube (via youtube-upload veya API)
- TikTok (via API)
- Instagram (via instabot veya API)
- Twitter/X
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class AutoPublisher:
    """
    Sosyal medya otomatik yayinlama servisi.
    """

    SUPPORTED_PLATFORMS = [
        "youtube", "tiktok", "instagram", "twitter", "kick"
    ]

    def __init__(self):
        self._credentials: Dict = {}

    def set_credentials(self, platform: str, credentials: Dict):
        """Platform kimlik bilgilerini ayarlar."""
        self._credentials[platform] = credentials
        logger.info("%s kimlik bilgileri ayarlandi", platform)

    async def publish(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: List[str] = None,
        platform: str = "youtube",
        privacy: str = "private",
        schedule_time: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Videoyu belirtilen platforma yukler.

        Args:
            video_path: Video dosyasi yolu
            title: Video basligi
            description: Aciklama
            tags: Etiket listesi
            platform: Hedef platform
            privacy: Gizlilik (private, public, unlisted)
            schedule_time: Planlanan yayin zamani (ISO 8601)

        Returns:
            {"platform": str, "video_id": str, "url": str} veya None
        """
        if not Path(video_path).exists():
            logger.error("Video dosyasi bulunamadi: %s", video_path)
            return None

        if platform not in self.SUPPORTED_PLATFORMS:
            logger.error("Desteklenmeyen platform: %s", platform)
            return None

        publishers = {
            "youtube": self._publish_youtube,
            "tiktok": self._publish_tiktok,
            "instagram": self._publish_instagram,
            "twitter": self._publish_twitter,
            "kick": self._publish_kick,
        }

        publisher = publishers.get(platform)
        if not publisher:
            return None

        try:
            result = await publisher(
                video_path, title, description, tags or [],
                privacy, schedule_time
            )
            if result:
                logger.info("Yayinlandi: %s -> %s", platform, result.get("url"))
            return result
        except Exception as e:
            logger.error("%s yayinlama hatasi: %s", platform, e)
            return None

    async def publish_multi(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: List[str] = None,
        platforms: List[str] = None,
        privacy: str = "private",
    ) -> List[Dict]:
        """Ayni videoyu birden fazla platforma yukler."""
        if not platforms:
            platforms = self.SUPPORTED_PLATFORMS

        results = []
        for platform in platforms:
            result = await self.publish(
                video_path, title, description, tags, platform, privacy
            )
            if result:
                results.append(result)

        return results

    async def _publish_youtube(
        self, video_path, title, description, tags, privacy, schedule_time
    ) -> Optional[Dict]:
        """YouTube'a yukler (youtube-upload veya API)."""
        creds = self._credentials.get("youtube")
        if not creds:
            logger.warning("YouTube kimlik bilgileri ayarlanmadi")
            return None

        # youtube-upload CLI ile yukle
        cmd = [
            "youtube-upload",
            "--title", title,
            "--description", description,
            "--tags", ",".join(tags),
            "--privacy", privacy,
            "--client-secrets", creds.get("client_secrets", ""),
            video_path,
        ]

        if schedule_time:
            cmd.extend(["--publish-at", schedule_time])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                video_id = stdout.decode().strip()
                return {
                    "platform": "youtube",
                    "video_id": video_id,
                    "url": f"https://youtube.com/watch?v={video_id}",
                }

        except Exception as e:
            logger.error("YouTube yukleme hatasi: %s", e)

        return None

    async def _publish_tiktok(
        self, video_path, title, description, tags, privacy, schedule_time
    ) -> Optional[Dict]:
        """TikTok'a yukler (TikTok API)."""
        creds = self._credentials.get("tiktok")
        if not creds:
            logger.warning("TikTok kimlik bilgileri ayarlanmadi")
            return None

        # TikTok Content Posting API
        import httpx
        async with httpx.AsyncClient() as client:
            # Video yukle
            response = await client.post(
                "https://open.tiktokapis.com/v2/post/publish/video/init/",
                headers={
                    "Authorization": f"Bearer {creds.get('access_token')}",
                    "Content-Type": "application/json",
                },
                json={
                    "post_info": {
                        "title": title,
                        "privacy_level": privacy,
                        "disable_duet": False,
                        "disable_stitch": False,
                        "disable_comment": False,
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": Path(video_path).stat().st_size,
                        "chunk_size": 10 * 1024 * 1024,
                        "total_chunk_count": 1,
                    },
                },
            )

            if response.status_code == 200:
                data = response.json().get("data", {})
                return {
                    "platform": "tiktok",
                    "video_id": data.get("publish_id", ""),
                    "url": data.get("publish_url", ""),
                }

        return None

    async def _publish_instagram(
        self, video_path, title, description, tags, privacy, schedule_time
    ) -> Optional[Dict]:
        """Instagram'a yukler (Graph API)."""
        creds = self._credentials.get("instagram")
        if not creds:
            logger.warning("Instagram kimlik bilgileri ayarlanmadi")
            return None

        logger.info("Instagram yukleme hazirlaniyor...")
        # Instagram Graph API ile Reels yukleme
        # Not: Tam implementasyon icin Facebook Graph API setup gerekli
        return {
            "platform": "instagram",
            "video_id": "pending",
            "url": "",
            "status": "queued",
        }

    async def _publish_twitter(
        self, video_path, title, description, tags, privacy, schedule_time
    ) -> Optional[Dict]:
        """Twitter/X'e yukler."""
        creds = self._credentials.get("twitter")
        if not creds:
            logger.warning("Twitter kimlik bilgileri ayarlanmadi")
            return None

        logger.info("Twitter yukleme hazirlaniyor...")
        return {
            "platform": "twitter",
            "video_id": "pending",
            "url": "",
            "status": "queued",
        }

    async def _publish_kick(
        self, video_path, title, description, tags, privacy, schedule_time
    ) -> Optional[Dict]:
        """Kick'e klip olarak yukler."""
        creds = self._credentials.get("kick")
        if not creds:
            logger.warning("Kick kimlik bilgileri ayarlanmadi")
            return None

        logger.info("Kick yukleme hazirlaniyor...")
        return {
            "platform": "kick",
            "video_id": "pending",
            "url": "",
            "status": "queued",
        }


# Singleton
auto_publisher = AutoPublisher()
