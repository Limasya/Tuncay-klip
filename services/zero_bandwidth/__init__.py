"""
Zero-Bandwidth Clip Engine
──────────────────────────
Sifir video indirme ile VOD analizi ve clip onerileri.

Modul yapisi:
- models.py: ClipSuggestion, VODAnalysis dataclass'lari
- vod_metadata.py: VOD metadata cekme, HLS source, VOD ID cikarma
- community_clips.py: Community clip islemleri, cluster, confidence
- llm_analysis.py: LLM ile analiz, prompt, JSON parse
- audio_fallback.py: Ses-only transkripsiyon
- alerting.py: Cloudflare tespit ve Discord alerting
- renderer.py: Clip render (FFmpeg ile segment indirme)

Konfigurasyon:
- CHANNEL: Kanal adi (varsayilan: thetuncay)
  Ortam degiskeninden okunur: ZERO_BANDWIDTH_CHANNEL
"""
from services.zero_bandwidth._config import CHANNEL
from services.zero_bandwidth.models import ClipSuggestion, VODAnalysis
from services.zero_bandwidth.clipper import ZeroBandwidthClipper

__all__ = ["ZeroBandwidthClipper", "ClipSuggestion", "VODAnalysis", "CHANNEL"]
