"""
Zero-Bandwidth Clip Engine — Cloudflare Alarm ve Tespit
──────────────────────────────────────────────────────
Cloudflare engelleme tespiti, Discord webhook alerting, spam cooldown.
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("zero_bandwidth_clipper")

# Cloudflare sabitleri — yeni tarayici surumleri guncellenecek
# curl_cffi docs: https://github.com/lexiforest/curl_cffi
# Yeni Chrome surumu ciktikca burasi guncellenmeli
CF_IMPERSONATE = "chrome124"

# FFmpeg icin Kick.com header'lari — curl_cffi'nin impersonate'i gibi
# zamanla Kick sunuculari bu User-Agent'i reddedebilir, guncel gerekebilir.
FFMPEG_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FFMPEG_REFERER = "https://kick.com/"

# Discord spam cooldown: 15 dakika
CF_DISCORD_COOLDOWN_SEC = 900


def check_cloudflare_block(
    status_code: int,
    response_text: str,
    cf_block_count: int,
    cf_alert_logged: bool,
    cf_last_discord_alert_time: float,
) -> tuple[bool, int, bool, float]:
    """Cloudflare tarafindan engellenip engellenmedigini kontrol et.

    Returns:
        (is_blocked, new_block_count, new_alert_logged, new_discord_alert_time)
    """
    if status_code in (403, 503):
        cf_block_count += 1
        new_discord_time = cf_last_discord_alert_time

        if not cf_alert_logged or cf_block_count % 10 == 0:
            logger.critical(
                "CLOUDFLARE ALARMI: %d kez engellendi! "
                "Impersonate surumu: %s. "
                "Yeni Chrome surumuna gecilmesi gerekebilir. "
                "Son yanit (ilk 200 karakter): %s",
                cf_block_count, CF_IMPERSONATE, response_text[:200],
            )
            cf_alert_logged = True
            new_discord_time = _send_cf_alert(
                "Cloudflare Engelleme",
                f"{cf_block_count} kez engellendi. "
                f"Impersonate: {CF_IMPERSONATE}. "
                f"Yeni Chrome surumuna gecilmesi gerekebilir.",
                cf_block_count, cf_last_discord_alert_time,
            )
        return True, cf_block_count, cf_alert_logged, new_discord_time

    # Challenge sayfasi kontrolu (CF bazen 200 dondurur ama challenge icerir)
    if status_code == 200 and response_text:
        text_lower = response_text[:1000].lower()
        if any(marker in text_lower for marker in [
            "cf-browser-verification",
            "cloudflare",
            "challenge-platform",
            "checking your browser",
            "just a moment",
        ]):
            cf_block_count += 1
            new_discord_time = cf_last_discord_alert_time
            logger.critical(
                "CLOUDFLARE CHALLENGE ALGILANDI (200 ama challenge sayfasi)! "
                "Impersonate: %s | Toplam engelleme: %d",
                CF_IMPERSONATE, cf_block_count,
            )
            new_discord_time = _send_cf_alert(
                "Cloudflare Challenge Sayfasi",
                f"200 dondu ama challenge sayfasi algilandi. "
                f"Impersonate: {CF_IMPERSONATE} | Toplam: {cf_block_count}",
                cf_block_count, cf_last_discord_alert_time,
            )
            return True, cf_block_count, True, new_discord_time

    return False, cf_block_count, cf_alert_logged, cf_last_discord_alert_time


def _send_cf_alert(
    title: str,
    message: str,
    block_count: int,
    last_discord_alert_time: float,
) -> float:
    """Cloudflare alarmi Discord webhook uzerinden gonder.

    Spam onleme: ayni hata tipi icin 15 dakikada sadece 1 mesaj gider.
    Returns: guncellenmiş last_discord_alert_time
    """
    now = time.monotonic()

    if (now - last_discord_alert_time) < CF_DISCORD_COOLDOWN_SEC:
        logger.debug(
            "Cloudflare Discord cooldown aktif (%.0f saniye kaldi), mesaj atlandi",
            CF_DISCORD_COOLDOWN_SEC - (now - last_discord_alert_time),
        )
        return last_discord_alert_time

    try:
        from config import get_settings
        settings = get_settings()
        webhook_url = settings.discord_webhook_url

        if not webhook_url:
            logger.debug("Discord webhook URL tanimli degil, Cloudflare alarmi atlandi")
            return last_discord_alert_time

        import httpx
        payload = {
            "embeds": [{
                "title": f"!! CLOUDFLARE ALARMI: {title}",
                "description": message,
                "color": 0xFF0000,
                "fields": [
                    {"name": "Impersonate", "value": CF_IMPERSONATE, "inline": True},
                    {"name": "Toplam Engelleme", "value": str(block_count), "inline": True},
                ],
                "footer": {"text": "Zero-Bandwidth Clipper"},
            }],
        }

        with httpx.Client(timeout=5) as client:
            resp = client.post(webhook_url, json=payload)
            if resp.status_code < 300:
                logger.info("Cloudflare alarmi Discord'a gonderildi")
                return now
            else:
                logger.warning("Discord webhook hatasi: %d", resp.status_code)

    except Exception as e:
        logger.warning("Cloudflare alarmi gonderilemedi: %s", e)

    return last_discord_alert_time


def get_cf_health(
    cf_block_count: int,
    cf_last_block_time: float,
) -> dict[str, Any]:
    """Cloudflare saglik durumu."""
    is_healthy = cf_block_count == 0 or (
        time.monotonic() - cf_last_block_time > 3600
    )
    recommendation = "Saglikli" if is_healthy else (
        f"Son engelleme {time.time() - cf_last_block_time:.0f} saniye once. "
        f"Impersonate versiyonunu guncelleyin: {CF_IMPERSONATE}"
    )
    return {
        "cf_block_count": cf_block_count,
        "cf_last_block_time": cf_last_block_time,
        "impersonate_version": CF_IMPERSONATE,
        "is_healthy": is_healthy,
        "recommendation": recommendation,
    }
