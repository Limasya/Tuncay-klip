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
