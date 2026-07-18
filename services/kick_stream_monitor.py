"""
Kick Stream Monitor
───────────────────
thetuncay kanalini surekli izler. Canli yayin basladiginda otomatik
orchestrator'i baslatir, hafizada stream capture yaparak klipler uretir.
Yayin bitince durdurur. ASLA VOD indirmez, ASLA disk'e stream yazmaz.

PC'de yer kaplamaz - sadece hafizada 30sn'lik ring buffer tutar.
Klipler uretildikten sonra data/clips/ altina yazilir (kucuk dosyalar).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from config import get_settings
from services.kick_api import kick_service

logger = logging.getLogger("kick_stream_monitor")


class KickStreamMonitor:
    """Kick canli yayin izleyici - otomatik orchestrator baslatma."""

    def __init__(self):
        self._settings = get_settings()
        self._slug = self._settings.kick_channel_slug
        self._monitor_task: Optional[asyncio.Task] = None
        self._is_running = False
        self._was_live = False
        self._orchestrator = None
        self._stream_url: Optional[str] = None
        self._check_interval = 30  # 30 saniyede bir kontrol

    async def start(self) -> bool:
        """Monitor'u baslat - arka planda surekli canli yayin kontrolu yapar."""
        if self._is_running:
            return False
        self._is_running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Kick Stream Monitor basladi: https://kick.com/{self._slug}")
        return True

    async def stop(self):
        """Monitor'u durdur."""
        self._is_running = False
        if self._orchestrator:
            try:
                await self._orchestrator.stop()
            except Exception as e:
                logger.debug("Orchestrator stop hatası (stop sırasında): %s", e)
            self._orchestrator = None
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        self._monitor_task = None
        logger.info("Kick Stream Monitor durduruldu")

    async def _monitor_loop(self):
        """Ana dongu - surekli canli yayin kontrolu."""
        while self._is_running:
            try:
                await self._check_and_react()
            except Exception as e:
                logger.error(f"Monitor dongu hatasi (devam ediliyor): {e}")
            await asyncio.sleep(self._check_interval)

    async def _check_and_react(self):
        """Kick API'den canli durumunu kontrol et ve tepki ver."""
        info = await kick_service.get_livestream_info()
        is_live = info.get("is_live", False)
        playback_url = info.get("playback_url", "")

        if is_live and not self._was_live:
            # YAYIN BASLADI!
            title = info.get("title", "")
            logger.info(f"YAYIN BASLADI: {title}")
            self._stream_url = playback_url
            if playback_url:
                await self._start_orchestrator(playback_url)
            else:
                logger.warning("Playback URL bulunamadi, orchestrator baslatilamadi")
            self._was_live = True

        elif not is_live and self._was_live:
            # YAYIN BITTI!
            logger.info("YAYIN BITTI - Orchestrator durduruluyor")
            await self._stop_orchestrator()
            self._was_live = False
            self._stream_url = None

    async def _start_orchestrator(self, stream_url: str):
        """Orchestrator'i stream URL ile baslat."""
        if self._orchestrator:
            await self._stop_orchestrator()

        from microservices.orchestrator import PipelineOrchestrator
        self._orchestrator = PipelineOrchestrator()
        await self._orchestrator.initialize()
        await self._orchestrator.start_stream(
            stream_url=stream_url,
            target_fps=2,
            buffer_seconds=30,
        )
        logger.info(f"Pipeline Orchestrator basladi: {stream_url[:60]}...")

    async def _stop_orchestrator(self):
        """Orchestrator'i durdur."""
        if self._orchestrator:
            try:
                await self._orchestrator.stop()
            except Exception as e:
                logger.error(f"Orchestrator stop hatasi: {e}")
            self._orchestrator = None

    def get_status(self) -> dict:
        """Monitor durumunu dondur."""
        orch_status = {}
        if self._orchestrator:
            try:
                orch_status = self._orchestrator.get_full_status()
            except Exception as e:
                logger.debug("Orchestrator durumu alınamadı: %s", e)

        return {
            "running": self._is_running,
            "channel": self._slug,
            "channel_url": f"https://kick.com/{self._slug}",
            "is_live": self._was_live,
            "stream_url": self._stream_url[:80] + "..." if self._stream_url and len(self._stream_url) > 80 else self._stream_url,
            "orchestrator": orch_status,
        }


kick_stream_monitor = KickStreamMonitor()