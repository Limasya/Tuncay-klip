"""
Faster Whisper Service
──────────────────────
OpenAI Whisper'ın CTranslate2 tabanlı 4x hızlı versiyonu.

Öncelik zinciri:
  1. Groq Whisper API (ücretsiz, 100x hızlı, bulut)
  2. faster-whisper (ücretsiz, local, 4x hızlı)
  3. openai-whisper (orijinal, local, ücretsiz)
  4. Mevcut services/subtitle_service.py (yedek)

Kullanım:
    from services.faster_whisper_service import faster_whisper
    result = await faster_whisper.transcribe("video.mp4", language="tr")
    srt_text = result["srt"]
    words = result["words"]
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("faster_whisper_service")


class FasterWhisperService:
    """
    Çok katmanlı Whisper servisi.

    Model boyutları (hız ↔ doğruluk):
      tiny   → En hızlı, temel doğruluk (~32MB)
      base   → Hızlı, iyi doğruluk (~74MB)  [DEFAULT]
      small  → Dengeli (~244MB)
      medium → Yüksek doğruluk (~769MB)
      large  → En yüksek doğruluk (~1.5GB)
      large-v3 → En güncel ve doğru (~1.5GB)
    """

    SUPPORTED_LANGUAGES = {
        "tr": "turkish", "en": "english", "de": "german",
        "fr": "french", "es": "spanish", "it": "italian",
        "pt": "portuguese", "ru": "russian", "ja": "japanese",
        "ko": "korean", "zh": "chinese",
    }

    def __init__(self):
        self._fw_model = None          # faster-whisper model
        self._fw_lock = asyncio.Lock()
        self._initialized = False
        self._backend = "none"         # groq / faster_whisper / whisper / subtitle_service

    @property
    def model_size(self) -> str:
        return os.environ.get("FASTER_WHISPER_MODEL", os.environ.get("WHISPER_MODEL_SIZE", "base"))

    @property
    def device(self) -> str:
        return os.environ.get("WHISPER_DEVICE", "auto")  # auto / cpu / cuda

    @property
    def compute_type(self) -> str:
        # float16 (GPU) veya int8 (CPU, daha hızlı)
        return os.environ.get("WHISPER_COMPUTE_TYPE", "auto")

    # ─── Backend Seçimi ──────────────────────────────────────────────────────

    def _get_compute_type(self, device: str) -> str:
        if self.compute_type != "auto":
            return self.compute_type
        return "float16" if device == "cuda" else "int8"

    def _load_faster_whisper(self) -> bool:
        """faster-whisper modelini yükle."""
        try:
            from faster_whisper import WhisperModel

            device = self.device
            if device == "auto":
                try:
                    import torch
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    device = "cpu"

            compute_type = self._get_compute_type(device)

            logger.info(
                "Loading faster-whisper model=%s device=%s compute=%s",
                self.model_size, device, compute_type,
            )
            self._fw_model = WhisperModel(
                self.model_size,
                device=device,
                compute_type=compute_type,
                download_root=os.path.join("models_store", "faster_whisper"),
            )
            self._backend = "faster_whisper"
            logger.info("✅ faster-whisper loaded (4x faster than original Whisper)")
            return True
        except ImportError:
            logger.info("faster-whisper not installed, trying alternatives")
            return False
        except Exception as e:
            logger.warning("faster-whisper load failed: %s", e)
            return False

    def _check_groq_available(self) -> bool:
        """Groq Whisper API kullanılabilir mi?"""
        key = os.environ.get("GROQ_API_KEY", "")
        if not key:
            return False
        # Groq'un Whisper desteği var mı kontrol et
        return True

    # ─── Transkripsiyon Metodları ────────────────────────────────────────────

    async def _transcribe_groq_from_bytes(
        self,
        audio_bytes: bytes,
        language: str,
        filename: str = "audio.wav",
    ) -> dict:
        """Groq Whisper'a byte[]'ten transkripsiyon (disk yok, memory only).

        Groq limiti 25MB. Büyük dosyaları parçalara bölüp her birini ayrı ayrı gönderir.
        """
        try:
            import aiohttp
            import io
            import json

            api_key = os.environ.get("GROQ_API_KEY", "")
            if not api_key:
                raise RuntimeError("GROQ_API_KEY yok")

            url = "https://api.groq.com/openai/v1/audio/transcriptions"
            GROQ_MAX_BYTES = 24 * 1024 * 1024  # 24MB safe limit (Groq limiti 25MB)

            all_words = []
            all_segments = []
            all_text_parts = []

            if len(audio_bytes) <= GROQ_MAX_BYTES:
                chunks = [(audio_bytes, filename, 0)]
            else:
                # WAV chunk: header 44 bytes, chunk boyutu 24MB'a yuvarla
                # 16kHz mono 16-bit = 32KB/sn → 24MB ≈ 768 saniye ≈ 12.8 dk
                chunk_duration_sec = int(GROQ_MAX_BYTES / 32000)
                chunk_samples = chunk_duration_sec * 16000
                chunk_bytes = chunk_samples * 2  # 16-bit = 2 bytes
                # WAV header 44 bytes
                header = audio_bytes[:44]
                pcm_data = audio_bytes[44:]

                chunks = []
                offset = 0
                chunk_idx = 0
                while offset < len(pcm_data):
                    chunk_pcm = pcm_data[offset:offset + chunk_bytes]
                    # Yeni WAV header oluştur
                    chunk_size = len(chunk_pcm) + 36
                    chunk_header = bytearray(header)
                    # dosya boyutunu güncelle
                    import struct
                    struct.pack_into('<I', chunk_header, 4, chunk_size)
                    struct.pack_into('<I', chunk_header, 40, len(chunk_pcm))
                    chunks.append((bytes(chunk_header) + chunk_pcm, f"chunk_{chunk_idx}.wav", offset / 32000))
                    offset += chunk_bytes
                    chunk_idx += 1

                logger.info("Ses %d parçaya bölündü (toplam %.1f MB, her parça ~%.0f dk)",
                            len(chunks), len(audio_bytes) / 1024 / 1024, chunk_duration_sec / 60)

            for chunk_idx, (chunk_data, chunk_name, time_offset) in enumerate(chunks):
                logger.info("Groq Whisper'a parca %d/%d gonderiliyor (%.1f MB, baslangic: %.0fs)...",
                            chunk_idx + 1, len(chunks), len(chunk_data) / 1024 / 1024, time_offset)

                async with aiohttp.ClientSession() as session:
                    form = aiohttp.FormData()
                    form.add_field("file", chunk_data, filename=chunk_name)
                    form.add_field("model", "whisper-large-v3-turbo")
                    if language and language != "auto":
                        form.add_field("language", language)
                    form.add_field("response_format", "verbose_json")
                    form.add_field("timestamp_granularities[]", "word")
                    form.add_field("timestamp_granularities[]", "segment")

                    headers = {"Authorization": f"Bearer {api_key}"}
                    async with session.post(url, data=form, headers=headers, timeout=180) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            logger.warning("Groq parca %d basarisiz (HTTP %d): %s", chunk_idx + 1, resp.status, text[:200])
                            continue
                        data = await resp.json()

                chunk_words = data.get("words", [])
                chunk_segments = data.get("segments", [])
                chunk_text = data.get("text", "")

                # Zaman damgalalarını offset'le
                for w in chunk_words:
                    w["start"] = round(w.get("start", 0) + time_offset, 3)
                    w["end"] = round(w.get("end", 0) + time_offset, 3)
                for s in chunk_segments:
                    s["start"] = round(s.get("start", 0) + time_offset, 3)
                    s["end"] = round(s.get("end", 0) + time_offset, 3)

                all_words.extend(chunk_words)
                all_segments.extend(chunk_segments)
                all_text_parts.append(chunk_text)
                logger.info("Groq parca %d tamamlandi: %d kelime, %d segment",
                            chunk_idx + 1, len(chunk_words), len(chunk_segments))

            if not all_words and not all_text_parts:
                raise RuntimeError("Tum Groq parcalari basarisiz")

            full_text = " ".join(all_text_parts)
            return {
                "text": full_text,
                "language": data.get("language", language) if data else language,
                "segments": all_segments,
                "words": all_words,
                "srt": self._segments_to_srt(all_segments),
                "backend": "groq_whisper",
                "model": "whisper-large-v3-turbo",
                "chunks": len(chunks),
            }
        except Exception as e:
            logger.warning("Groq Whisper (bytes) failed: %s", e)
            raise

    async def _transcribe_groq(
        self,
        audio_path: str,
        language: str,
    ) -> dict:
        """Groq Whisper API ile transkripsiyon (ücretsiz, çok hızlı)."""
        try:
            import aiohttp
            import json

            api_key = os.environ.get("GROQ_API_KEY", "")
            url = "https://api.groq.com/openai/v1/audio/transcriptions"

            async with aiohttp.ClientSession() as session:
                with open(audio_path, "rb") as f:
                    form = aiohttp.FormData()
                    form.add_field("file", f, filename=Path(audio_path).name)
                    form.add_field("model", "whisper-large-v3-turbo")
                    if language and language != "auto":
                        form.add_field("language", language)
                    form.add_field("response_format", "verbose_json")
                    form.add_field("timestamp_granularities[]", "word")
                    form.add_field("timestamp_granularities[]", "segment")

                    headers = {"Authorization": f"Bearer {api_key}"}
                    async with session.post(url, data=form, headers=headers, timeout=120) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            raise RuntimeError(f"Groq Whisper HTTP {resp.status}: {text[:200]}")
                        data = await resp.json()

            segments = data.get("segments", [])
            words = data.get("words", [])
            full_text = data.get("text", "")

            return {
                "text": full_text,
                "language": data.get("language", language),
                "segments": segments,
                "words": words,
                "srt": self._segments_to_srt(segments),
                "backend": "groq_whisper",
                "model": "whisper-large-v3-turbo",
            }
        except Exception as e:
            logger.warning("Groq Whisper failed: %s", e)
            raise

    async def _transcribe_faster_whisper(
        self,
        audio_path: str,
        language: str,
    ) -> dict:
        """faster-whisper ile local transkripsiyon."""
        def _run():
            lang = language if language != "auto" else None
            segments_iter, info = self._fw_model.transcribe(
                audio_path,
                language=lang,
                beam_size=5,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            segments = []
            words_out = []
            full_text_parts = []

            for seg in segments_iter:
                seg_dict = {
                    "id": seg.id,
                    "start": round(seg.start, 3),
                    "end": round(seg.end, 3),
                    "text": seg.text.strip(),
                    "avg_logprob": round(seg.avg_logprob, 3),
                    "no_speech_prob": round(seg.no_speech_prob, 3),
                }
                segments.append(seg_dict)
                full_text_parts.append(seg.text.strip())

                if seg.words:
                    for w in seg.words:
                        words_out.append({
                            "word": w.word.strip(),
                            "start": round(w.start, 3),
                            "end": round(w.end, 3),
                            "probability": round(w.probability, 3),
                        })

            return {
                "text": " ".join(full_text_parts),
                "language": info.language,
                "language_probability": round(info.language_probability, 3),
                "duration": round(info.duration, 2),
                "segments": segments,
                "words": words_out,
                "srt": self._segments_to_srt(segments),
                "backend": "faster_whisper",
                "model": self.model_size,
            }

        return await asyncio.to_thread(_run)

    async def _transcribe_fallback(
        self,
        audio_path: str,
        language: str,
    ) -> dict:
        """Mevcut subtitle_service'e fallback."""
        try:
            from services.subtitle_service import subtitle_service
            result = await subtitle_service.transcribe(audio_path, language=language)
            if isinstance(result, dict):
                result["backend"] = "subtitle_service"
            else:
                result = {"text": str(result), "backend": "subtitle_service", "srt": ""}
            return result
        except Exception as e:
            logger.warning("Subtitle service fallback failed: %s", e)
            return {
                "text": "",
                "srt": "",
                "segments": [],
                "words": [],
                "backend": "failed",
                "error": str(e),
            }

    # ─── Ana API ─────────────────────────────────────────────────────────────

    async def transcribe(
        self,
        video_or_audio_path: str,
        language: str = "auto",
        extract_audio: bool = True,
        word_timestamps: bool = False,
    ) -> dict:
        """
        Video/ses dosyasını transkribe et.

        Args:
            video_or_audio_path: Video veya ses dosyası yolu
            language: Dil kodu ("tr", "en", "auto")
            extract_audio: Video'dan ses çıkar (FFmpeg gerekir)

        Returns:
            {
                "text": tam metin,
                "srt": SRT formatı altyazı,
                "segments": [...],
                "words": [...],
                "language": tespit edilen dil,
                "backend": kullanılan backend,
                "model": kullanılan model,
            }
        """
        audio_path = video_or_audio_path

        # Video'dan ses çıkar
        if extract_audio and not video_or_audio_path.lower().endswith(
            (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus")
        ):
            audio_path = await self._extract_audio(video_or_audio_path)

        lang_code = language
        if language == "auto":
            lang_code = "auto"
        elif language in self.SUPPORTED_LANGUAGES:
            lang_code = language

        # ── 1. Groq Whisper (ücretsiz, cloud, çok hızlı) ──
        if self._check_groq_available():
            try:
                logger.info("Transcribing with Groq Whisper (free, fast)...")
                result = await self._transcribe_groq(audio_path, lang_code)
                logger.info("✅ Groq Whisper: %d chars, lang=%s", len(result["text"]), result.get("language"))
                return result
            except Exception as e:
                logger.warning("Groq Whisper failed, trying faster-whisper: %s", e)

        # ── 2. faster-whisper (local, 4x hızlı) ──
        async with self._fw_lock:
            if self._fw_model is None:
                self._load_faster_whisper()

        if self._fw_model is not None:
            try:
                logger.info("Transcribing with faster-whisper model=%s...", self.model_size)
                result = await self._transcribe_faster_whisper(audio_path, lang_code)
                logger.info(
                    "✅ faster-whisper: %d chars, lang=%s, %.1fs",
                    len(result["text"]), result.get("language"), result.get("duration", 0),
                )
                return result
            except Exception as e:
                logger.warning("faster-whisper failed, falling back: %s", e)

        # ── 3. Mevcut subtitle_service fallback ──
        logger.info("Falling back to subtitle_service...")
        return await self._transcribe_fallback(audio_path, lang_code)

    async def _extract_audio(self, video_path: str) -> str:
        """FFmpeg ile video'dan ses çıkar."""
        tmp_dir = tempfile.mkdtemp()
        audio_path = os.path.join(tmp_dir, "audio.wav")

        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-i", video_path,
                "-ac", "1", "-ar", "16000",
                "-f", "wav", audio_path,
                "-y", "-loglevel", "error",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                logger.warning("FFmpeg audio extraction failed: %s", stderr.decode()[:200])
                return video_path  # Ham video ile devam et
            return audio_path
        except Exception as e:
            logger.warning("Audio extraction failed: %s", e)
            return video_path

    @staticmethod
    def _segments_to_srt(segments: list[dict]) -> str:
        """Segment listesini SRT formatına çevir."""
        lines = []
        for i, seg in enumerate(segments, 1):
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            text = seg.get("text", "").strip()
            if not text:
                continue

            def fmt(secs: float) -> str:
                h = int(secs // 3600)
                m = int((secs % 3600) // 60)
                s = int(secs % 60)
                ms = int((secs % 1) * 1000)
                return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

            lines.append(str(i))
            lines.append(f"{fmt(start)} --> {fmt(end)}")
            lines.append(text)
            lines.append("")

        return "\n".join(lines)

    async def get_status(self) -> dict:
        """Servis durumunu döndür."""
        return {
            "backend": self._backend,
            "model_size": self.model_size,
            "device": self.device,
            "model_loaded": self._fw_model is not None,
            "groq_available": self._check_groq_available(),
            "supported_languages": list(self.SUPPORTED_LANGUAGES.keys()),
            "models_dir": os.path.join("models_store", "faster_whisper"),
        }


# Singleton
faster_whisper = FasterWhisperService()
