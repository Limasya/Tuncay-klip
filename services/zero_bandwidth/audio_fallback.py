"""
Zero-Bandwidth Clip Engine — Ses-Only Fallback
───────────────────────────────────────────────
Sadece sesi indirerek transkripsiyon yapma (VOD'larda community clip yoksa).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("zero_bandwidth_clipper")


async def transcribe_audio_only(
    hls_url: str,
    duration_sec: float,
    chunk_minutes: float = 5.0,
) -> Optional[str]:
    """HLS stream'den sadece sesi cek ve transkribe et.

    AAC 64kbps ile ~28.8 MB/saat. 5 dakikalik chunk'larla calisir.
    Toplam bant genisligi: ~2.4 MB/saat.
    """
    try:
        import subprocess
        import tempfile

        audio_chunks_dir = Path(tempfile.mkdtemp(prefix="zw_audio_"))
        chunk_texts: list[str] = []

        # Chunk sayisini hesapla
        chunk_sec = chunk_minutes * 60
        num_chunks = max(1, int(duration_sec / chunk_sec) + 1)

        logger.info(
            "Ses-only transkripsiyon: %d chunk (%.0f sn aralikla), toplam %.0f sn",
            num_chunks, chunk_sec, duration_sec,
        )

        for ci in range(num_chunks):
            start = ci * chunk_sec
            chunk_path = audio_chunks_dir / f"chunk_{ci:03d}.aac"

            # FFmpeg ile sadece sesi indir
            cmd = [
                "ffmpeg", "-y",
                "-headers", "User-Agent: Mozilla/5.0\r\nReferer: https://kick.com/\r\n",
                "-ss", str(start),
                "-i", hls_url,
                "-t", str(chunk_sec),
                "-vn",
                "-c:a", "aac", "-b:a", "64k",
                str(chunk_path),
            ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=120)

                if not chunk_path.exists() or chunk_path.stat().st_size < 1024:
                    continue
            except asyncio.TimeoutError:
                logger.warning("Chunk %d indirme timeout", ci)
                continue

            # Transkripsiyon
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel("tiny", device="cpu", compute_type="int8")
                segments, _ = model.transcribe(
                    str(chunk_path), language="tr",
                    beam_size=1, vad_filter=True,
                )
                chunk_text = " ".join(seg.text for seg in segments)
                if chunk_text.strip():
                    chunk_texts.append(f"[{start//60:.0f}dk] {chunk_text.strip()}")
            except Exception as e:
                logger.warning("Chunk %d transkripsiyon hatasi: %s", ci, e)

            # Gecici dosyayi sil
            try:
                chunk_path.unlink(missing_ok=True)
            except Exception:
                pass

        # Gecici dizini temizle
        try:
            audio_chunks_dir.rmdir()
        except Exception:
            pass

        if chunk_texts:
            full_text = "\n".join(chunk_texts)
            logger.info(
                "Ses-only transkripsiyon tamamlandi: %d chunk, %d karakter",
                len(chunk_texts), len(full_text),
            )
            return full_text

        logger.warning("Ses-only transkripsiyon: hicbir metin cikarilamadi")
        return None

    except Exception as e:
        logger.error("Ses-only transkripsiyon hatasi: %s", e)
        return None
