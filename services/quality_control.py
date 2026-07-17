"""
Post-render kalite kontrol (QC) motoru.
Render sonrası otomatik kalite doğrulama.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class QCIssue:
    """QC sorunu."""
    severity: str   # "error", "warning", "info"
    category: str   # "video", "audio", "format", "content"
    message: str
    value: Optional[str] = None
    threshold: Optional[str] = None


@dataclass
class QCReport:
    """QC raporu."""
    passed: bool
    score: float           # 0-100
    issues: List[QCIssue] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)

    def summary(self) -> str:
        errors = sum(1 for i in self.issues if i.severity == "error")
        warnings = sum(1 for i in self.issues if i.severity == "warning")
        return (
            f"QC {'BASARILI' if self.passed else 'BASARISIZ'} "
            f"(skor: {self.score:.0f}/100, "
            f"hata: {errors}, uyari: {warnings})"
        )


class QualityControl:
    """
    Post-render kalite kontrol motoru.
    """

    def __init__(self):
        self._checks = [
            self._check_video_stream,
            self._check_audio_stream,
            self._check_duration,
            self._check_resolution,
            self._check_bitrate,
            self._check_loudness,
            self._check_black_frames,
            self._check_frozen_frames,
        ]

    async def run_qc(
        self,
        video_path: str,
        expected_duration: Optional[float] = None,
        expected_width: int = 1080,
        expected_height: int = 1920,
        max_duration_diff: float = 1.0,
    ) -> QCReport:
        """
        Video dosyası üzerinde QC kontrolü çalıştırır.
        """
        issues = []
        metadata = {}

        # ffprobe ile bilgi al
        info = await self._probe_video(video_path)
        if not info:
            return QCReport(
                passed=False,
                score=0,
                issues=[QCIssue("error", "format", "ffprobe bilgisi alınamadı")],
            )

        metadata["probe"] = info

        # Tüm kontrolleri çalıştır
        for check in self._checks:
            try:
                result = await check(
                    video_path, info,
                    expected_duration=expected_duration,
                    expected_width=expected_width,
                    expected_height=expected_height,
                    max_duration_diff=max_duration_diff,
                )
                if result:
                    issues.extend(result)
            except Exception as e:
                issues.append(QCIssue(
                    "warning", "check", f"Kontrol hatası: {e}"
                ))

        # Skor hesapla
        score = self._calculate_score(issues)
        passed = not any(i.severity == "error" for i in issues)

        report = QCReport(
            passed=passed,
            score=score,
            issues=issues,
            metadata=metadata,
        )

        logger.info("QC tamamlandı: %s", report.summary())
        return report

    async def _check_video_stream(
        self, path: str, info: Dict, **kwargs
    ) -> List[QCIssue]:
        """Video stream kontrolü."""
        issues = []
        streams = info.get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]

        if not video_streams:
            issues.append(QCIssue("error", "video", "Video stream bulunamadı"))
            return issues

        vs = video_streams[0]
        codec = vs.get("codec_name", "")

        if codec not in ("h264", "hevc", "vp9", "av1"):
            issues.append(QCIssue(
                "warning", "video",
                f"Bilinmeyen video codec: {codec}"
            ))

        # FPS kontrolü
        fps_str = vs.get("r_frame_rate", "0/1")
        try:
            num, den = fps_str.split("/")
            fps = int(num) / int(den)
            if fps < 24 or fps > 60:
                issues.append(QCIssue(
                    "warning", "video",
                    f"Olağandışı FPS: {fps:.1f}"
                ))
        except (ValueError, ZeroDivisionError):
            pass

        return issues

    async def _check_audio_stream(
        self, path: str, info: Dict, **kwargs
    ) -> List[QCIssue]:
        """Audio stream kontrolü."""
        issues = []
        streams = info.get("streams", [])
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        if not audio_streams:
            issues.append(QCIssue("error", "audio", "Audio stream bulunamadı"))
            return issues

        aus = audio_streams[0]
        codec = aus.get("codec_name", "")

        if codec not in ("aac", "mp3", "opus", "flac", "pcm_s16le"):
            issues.append(QCIssue(
                "warning", "audio",
                f"Bilinmeyen audio codec: {codec}"
            ))

        # Sample rate kontrolü
        sr = int(aus.get("sample_rate", 0))
        if sr and sr not in (44100, 48000, 96000):
            issues.append(QCIssue(
                "warning", "audio",
                f"Olağandışı sample rate: {sr}"
            ))

        return issues

    async def _check_duration(
        self, path: str, info: Dict,
        expected_duration: Optional[float] = None,
        max_duration_diff: float = 1.0,
        **kwargs
    ) -> List[QCIssue]:
        """Süre kontrolü."""
        issues = []
        fmt = info.get("format", {})
        duration = float(fmt.get("duration", 0))

        if duration <= 0:
            issues.append(QCIssue("error", "format", "Süre 0 veya negatif"))
        elif duration > 600:
            issues.append(QCIssue("warning", "format", f"Çok uzun süre: {duration:.0f}s"))

        if expected_duration and duration > 0:
            diff = abs(duration - expected_duration)
            if diff > max_duration_diff:
                issues.append(QCIssue(
                    "warning", "format",
                    f"Süre farkı: {diff:.1f}s (beklenen: {expected_duration:.1f})",
                    value=str(duration),
                    threshold=f"±{max_duration_diff}s",
                ))

        return issues

    async def _check_resolution(
        self, path: str, info: Dict,
        expected_width: int = 1080,
        expected_height: int = 1920,
        **kwargs
    ) -> List[QCIssue]:
        """Çözünürlük kontrolü."""
        issues = []
        streams = info.get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]

        if video_streams:
            vs = video_streams[0]
            w = int(vs.get("width", 0))
            h = int(vs.get("height", 0))

            if w != expected_width or h != expected_height:
                issues.append(QCIssue(
                    "warning", "video",
                    f"Çözünürlük uyumsuz: {w}x{h} != {expected_width}x{expected_height}",
                    value=f"{w}x{h}",
                    threshold=f"{expected_width}x{expected_height}",
                ))

            if w < 640 or h < 480:
                issues.append(QCIssue(
                    "warning", "video",
                    f"Çok düşük çözünürlük: {w}x{h}"
                ))

        return issues

    async def _check_bitrate(
        self, path: str, info: Dict, **kwargs
    ) -> List[QCIssue]:
        """Bitrate kontrolü."""
        issues = []
        fmt = info.get("format", {})
        bitrate = int(fmt.get("bit_rate", 0))

        if bitrate > 0:
            bitrate_mbps = bitrate / 1_000_000
            if bitrate_mbps > 20:
                issues.append(QCIssue(
                    "warning", "format",
                    f"Yüksek bitrate: {bitrate_mbps:.1f} Mbps"
                ))
            elif bitrate_mbps < 0.5:
                issues.append(QCIssue(
                    "warning", "format",
                    f"Düşük bitrate: {bitrate_mbps:.2f} Mbps"
                ))

        return issues

    async def _check_loudness(
        self, path: str, info: Dict, **kwargs
    ) -> List[QCIssue]:
        """Gerçek LUFS loudness kontrolü (FFmpeg ebur128)."""
        issues = []
        try:
            cmd = [
                "ffmpeg", "-i", path,
                "-af", "ebur128=peak=true",
                "-f", "null", "-"
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            output = stderr.decode(errors="ignore")
            # ebur128 son satırda özet verir: I: -XX.X LUFS
            for line in output.splitlines():
                if "Integrated loudness" in line or "I:" in line and "LUFS" in line:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == "I:" and i + 1 < len(parts):
                            try:
                                lufs = float(parts[i + 1])
                                # TikTok/YouTube öneri: -14 LUFS ±2
                                if lufs < -24:
                                    issues.append(QCIssue(
                                        "warning", "audio",
                                        f"Ses çok düşük: {lufs:.1f} LUFS (hedef: -14)",
                                        value=str(lufs), threshold="-24"
                                    ))
                                elif lufs > -6:
                                    issues.append(QCIssue(
                                        "error", "audio",
                                        f"Ses çok yüksek/clipping riski: {lufs:.1f} LUFS",
                                        value=str(lufs), threshold="-6"
                                    ))
                            except (ValueError, IndexError):
                                pass
        except Exception as e:
            logger.warning("Loudness check failed: %s", e)
        return issues

    async def _check_black_frames(
        self, path: str, info: Dict, **kwargs
    ) -> List[QCIssue]:
        """Gerçek siyah kare kontrolü (FFmpeg blackdetect)."""
        issues = []
        try:
            cmd = [
                "ffmpeg", "-i", path,
                "-vf", "blackdetect=d=0.5:pix_th=0.10",
                "-an", "-f", "null", "-"
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            output = stderr.decode(errors="ignore")
            black_count = output.count("black_start")
            if black_count > 3:
                issues.append(QCIssue(
                    "warning", "video",
                    f"{black_count} adet siyah kare bölümü tespit edildi",
                    value=str(black_count)
                ))
        except Exception as e:
            logger.warning("Black frame check failed: %s", e)
        return issues

    async def _check_frozen_frames(
        self, path: str, info: Dict, **kwargs
    ) -> List[QCIssue]:
        """Gerçek donmuş kare kontrolü (FFmpeg freezedetect)."""
        issues = []
        try:
            cmd = [
                "ffmpeg", "-i", path,
                "-vf", "freezedetect=n=-60dB:d=1.0",
                "-an", "-f", "null", "-"
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            output = stderr.decode(errors="ignore")
            freeze_count = output.count("freeze_start")
            if freeze_count > 0:
                issues.append(QCIssue(
                    "warning", "video",
                    f"{freeze_count} adet donmuş kare bölümü tespit edildi",
                    value=str(freeze_count)
                ))
        except Exception as e:
            logger.warning("Frozen frame check failed: %s", e)
        return issues

    def _calculate_score(self, issues: List[QCIssue]) -> float:
        """QC skoru hesaplar (0-100)."""
        score = 100.0

        for issue in issues:
            if issue.severity == "error":
                score -= 25
            elif issue.severity == "warning":
                score -= 5
            elif issue.severity == "info":
                score -= 1

        return max(0, score)

    async def _probe_video(self, path: str) -> Optional[Dict]:
        """ffprobe ile video bilgisi alır."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return json.loads(stdout.decode())
        except Exception as e:
            logger.error("ffprobe hatası: %s", e)
            return None


# Singleton
quality_control = QualityControl()
