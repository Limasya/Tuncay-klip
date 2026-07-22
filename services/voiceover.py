"""
Voice-Over Pipeline Servisi
opensource-clipping voiceover.py'den adaptasyon.
AI ile script uretimi + edge-tts ile ses sentezi.
"""
import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_EDGE_TTS_AVAILABLE = False
try:
    import edge_tts
    _EDGE_TTS_AVAILABLE = True
except ImportError:
    pass


@dataclass
class VoiceOverConfig:
    """Voice-over konfigurasyonu."""
    voice: str = "tr-TR-AhmetNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    original_audio_duck: float = 0.15
    voiceover_volume: float = 1.0
    output_format: str = "mp3"


@dataclass
class VoiceOverResult:
    """Voice-over sonucu."""
    audio_path: str
    subtitle_path: Optional[str] = None
    word_timings: Optional[list] = None
    success: bool = True
    error: Optional[str] = None


async def synthesize_speech(
    text: str,
    output_path: str,
    config: Optional[VoiceOverConfig] = None,
) -> VoiceOverResult:
    """
    edge-tts ile metni sese cevir.
    """
    if not _EDGE_TTS_AVAILABLE:
        return VoiceOverResult(
            audio_path="", success=False,
            error="edge-tts yuklenemedi. pip install edge-tts"
        )

    if config is None:
        config = VoiceOverConfig()

    try:
        communicate = edge_tts.Communicate(text, config.voice, rate=config.rate, volume=config.volume)
        await communicate.save(output_path)
        logger.info("Voice-over seslendirme tamamlandi: %s", output_path)
        return VoiceOverResult(audio_path=output_path)
    except Exception as e:
        logger.error("Voice-over sentez hatasi: %s", e)
        return VoiceOverResult(audio_path="", success=False, error=str(e))


async def synthesize_with_word_timings(
    text: str,
    audio_path: str,
    subtitle_path: Optional[str] = None,
    config: Optional[VoiceOverConfig] = None,
) -> VoiceOverResult:
    """
    edge-tts ile kelime bazli zamanlama bilgisi ile ses sentezi.
    """
    if not _EDGE_TTS_AVAILABLE:
        return VoiceOverResult(
            audio_path="", success=False,
            error="edge-tts yuklenemedi. pip install edge-tts"
        )

    if config is None:
        config = VoiceOverConfig()

    try:
        communicate = edge_tts.Communicate(text, config.voice, rate=config.rate, volume=config.volume)
        word_timings = []

        with open(audio_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    word_timings.append({
                        "word": chunk["text"],
                        "start": chunk["offset"] / 10_000_000,
                        "duration": chunk["duration"] / 10_000_000,
                    })

        if subtitle_path and word_timings:
            _write_srt_from_timings(word_timings, subtitle_path)

        logger.info("Voice-over kelime zamanlama ile tamamlandi: %s (%d kelime)", audio_path, len(word_timings))
        return VoiceOverResult(audio_path=audio_path, subtitle_path=subtitle_path, word_timings=word_timings)

    except Exception as e:
        logger.error("Voice-over sentez hatasi: %s", e)
        return VoiceOverResult(audio_path="", success=False, error=str(e))


def _write_srt_from_timings(timings: list, output_path: str) -> None:
    """Kelime zamanlamalarindan SRT altyazi uret."""
    lines = []
    for i, t in enumerate(timings):
        start = t["start"]
        end = start + t["duration"]
        lines.append(f"{i + 1}")
        lines.append(f"{_srt_time(start)} --> {_srt_time(end)}")
        lines.append(t["word"])
        lines.append("")
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")


def _srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


async def generate_voiceover_script(
    transcript: str,
    llm_callback=None,
    language: str = "tr",
) -> str:
    """
    Transcript'ten voice-over script uretir (LLM callback ile veya basit fallback).
    """
    if llm_callback:
        try:
            prompt = (
                f"Aşağıdaki transkripsiyonu seslendirme scriptine dönüştür. "
                f"Kısa, etkileyici ve doğal bir anlatım oluştur. "
                f"Dil: {language}\n\nTranskripsiyon:\n{transcript[:2000]}"
            )
            result = await llm_callback(prompt)
            if result and len(result.strip()) > 10:
                return result.strip()
        except Exception as e:
            logger.warning("LLM script uretimi basarisiz, fallback kullaniliyor: %s", e)

    sentences = [s.strip() for s in transcript.replace(".", ".").split(".") if s.strip()]
    summary = ". ".join(sentences[:3])
    if language == "tr":
        return f"İşte bu bölümün özeti: {summary}"
    return f"Here is a summary of this section: {summary}"
