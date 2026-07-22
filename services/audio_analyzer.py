"""
Ses Analiz ve Auto-Zoom Servisi
─────────────────────────────────
Videodaki sesi analiz edip ani ses yükselmelerini (bağırma, gülme vb.) 
tespit eder. Bu zirveler (peaks) Auto-Zoom (Punch-in) filtresi için
zaman damgaları (timestamps) sağlar.
"""
import asyncio
import logging
import re
from typing import Dict, List, Any

logger = logging.getLogger("audio_analyzer")

class AudioAnalyzer:
    def __init__(self, peak_threshold: float = -10.0):
        self.peak_threshold = peak_threshold  # dB cinsinden (örn: -10 dB üstü bağırış)

    async def get_loud_peaks(self, video_path: str) -> Dict[str, Any]:
        """
        FFmpeg ebur128 filtresi ile videonun sesini saniye saniye analiz eder,
        belirli bir threshold üzerindeki yüksek sesli anları döndürür.
        """
        logger.info("Analyzing audio peaks for %s", video_path)
        
        # astats ile kısa süreli peak'leri de bulabiliriz ama ebur128 (LUFS)
        # algılanan ses şiddeti için daha stabildir. Veya ebur128 ile deneyelim.
        # Daha hızlı analiz için aformat=channel_layouts=mono ekliyoruz.
        cmd = [
            "ffmpeg", "-i", video_path,
            "-filter_complex", "ebur128=meter=18",
            "-f", "null", "-"
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            
            output = stderr.decode()
            peaks = self._parse_ebur128(output)
            
            return {
                "success": True,
                "peaks": peaks
            }

        except Exception as e:
            logger.error("Audio analysis failed: %s", e)
            return {"error": str(e)}

    async def get_voice_activity(self, video_path: str) -> Dict[str, Any]:
        """Return energy-based voice/activity ranges by inverting silence ranges."""
        duration = await self._probe_duration(video_path)
        if duration <= 0:
            return {"success": False, "segments": [], "speech_ratio": 0.0}

        cmd = [
            "ffmpeg", "-hide_banner", "-i", video_path,
            "-af", "silencedetect=noise=-35dB:d=0.35",
            "-f", "null", "-",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            output = stderr.decode(errors="replace")
            starts = [float(value) for value in re.findall(r"silence_start:\s*([\d.]+)", output)]
            ends = [float(value) for value in re.findall(r"silence_end:\s*([\d.]+)", output)]
            silences = list(zip(starts, ends))

            active = []
            cursor = 0.0
            for start, end in silences:
                if start - cursor >= 0.2:
                    active.append({"start": round(cursor, 2), "end": round(start, 2)})
                cursor = max(cursor, end)
            if duration - cursor >= 0.2:
                active.append({"start": round(cursor, 2), "end": round(duration, 2)})

            active_duration = sum(segment["end"] - segment["start"] for segment in active)
            return {
                "success": True,
                "segments": active,
                "speech_ratio": round(active_duration / duration, 3),
                "method": "ffmpeg_energy_vad",
            }
        except Exception as exc:
            logger.error("Voice activity analysis failed: %s", exc)
            return {"success": False, "segments": [], "speech_ratio": 0.0}

    @staticmethod
    async def _probe_duration(video_path: str) -> float:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        try:
            return float(stdout.decode().strip())
        except (TypeError, ValueError):
            return 0.0

    def _parse_ebur128(self, output: str) -> List[Dict[str, float]]:
        """ebur128 çıktısından t (saniye) ve S (momentary loudness) değerlerini ayrıştırır."""
        peaks = []
        in_peak = False
        peak_start = 0.0
        
        # Çıktı formatı örneği: [Parsed_ebur128_0 @ 0x...] t: 1.234  S: -12.3 LUFS  ...
        pattern = re.compile(r"t:\s*([\d\.]+)\s*M:\s*([-\d\.]+)")
        
        for line in output.split('\n'):
            match = pattern.search(line)
            if match:
                time_sec = float(match.group(1))
                momentary_lufs = float(match.group(2))
                
                # Sesi yüksek mi? (örn: -10 LUFS)
                # LUFS eksi değerdir, 0'a ne kadar yakınsa o kadar yüksektir.
                if momentary_lufs > self.peak_threshold:
                    if not in_peak:
                        in_peak = True
                        peak_start = time_sec
                else:
                    if in_peak:
                        in_peak = False
                        peak_end = time_sec
                        # Sadece belirli bir sürenin (örn: 0.2s) üstündeki tepkileri al
                        if peak_end - peak_start > 0.2:
                            peaks.append({
                                "start": round(peak_start, 2),
                                "end": round(peak_end, 2)
                            })

        # Dosya yüksek sesle bitiyorsa son peak'i kapat
        if in_peak:
             peaks.append({
                 "start": round(peak_start, 2),
                 "end": round(peak_start + 1.0, 2)
             })

        return peaks

# Singleton
audio_analyzer = AudioAnalyzer(peak_threshold=-15.0)  # Threshold testlere göre ayarlanabilir
