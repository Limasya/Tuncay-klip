"""
Sessizlik Silici (Auto-Editor Logic)
────────────────────────────────────
Videodaki ses seviyelerini analiz edip (FFmpeg silencedetect)
kimsenin konuşmadığı, sessiz ölü anları bulur ve bunları 
atlayarak jump-cut yapılmış daha hızlı (fast-paced) bir 
klip edit planı üretir.
"""
import asyncio
import logging
import re
from typing import Dict, List, Any

logger = logging.getLogger("silence_remover")


class SilenceRemover:
    def __init__(self, silence_thresh: str = "-35dB", silence_duration: float = 0.5):
        self.silence_thresh = silence_thresh
        self.silence_duration = silence_duration

    async def detect_silences(self, video_path: str) -> Dict[str, Any]:
        """
        Videoyu FFmpeg silencedetect ile tarar ve sessiz anların
        (start, end, duration) listesini döndürür.
        """
        logger.info("Detecting silences in %s", video_path)
        
        cmd = [
            "ffmpeg", "-i", video_path,
            "-af", f"silencedetect=noise={self.silence_thresh}:d={self.silence_duration}",
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
            silences = self._parse_silencedetect_output(output)
            
            # Videonun toplam süresini de alalım
            duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", output)
            total_duration = 0.0
            if duration_match:
                h, m, s = duration_match.groups()
                total_duration = int(h)*3600 + int(m)*60 + float(s)
                
            return {
                "success": True,
                "silences": silences,
                "total_duration": total_duration
            }

        except Exception as e:
            logger.error("Silence detection failed: %s", e)
            return {"error": str(e)}

    def _parse_silencedetect_output(self, output: str) -> List[Dict[str, float]]:
        """FFmpeg stderr çıktısındaki silence_start ve silence_end satırlarını okur."""
        silences = []
        current_start = None
        
        for line in output.split('\n'):
            if "silence_start:" in line:
                match = re.search(r"silence_start:\s*([\d\.]+)", line)
                if match:
                    current_start = float(match.group(1))
            elif "silence_end:" in line:
                match = re.search(r"silence_end:\s*([\d\.]+)\s*\|\s*silence_duration:\s*([\d\.]+)", line)
                if match and current_start is not None:
                    end_time = float(match.group(1))
                    duration = float(match.group(2))
                    silences.append({
                        "start": current_start,
                        "end": end_time,
                        "duration": duration
                    })
                    current_start = None
                    
        return silences

    def generate_jumpcut_filter(self, total_duration: float, silences: List[Dict[str, float]]) -> str:
        """
        Sessizlik listesini alarak FFmpeg için trim ve concat filtresi üretir.
        """
        if not silences:
            return ""

        # Saklanacak anları (konuşma olan yerleri) hesapla
        keep_segments = []
        last_end = 0.0
        
        for s in silences:
            if s["start"] > last_end:
                keep_segments.append((last_end, s["start"]))
            last_end = s["end"]
            
        if last_end < total_duration:
            keep_segments.append((last_end, total_duration))

        # FFmpeg filter dizisini oluştur
        filter_parts = []
        concat_inputs = ""
        for i, (start, end) in enumerate(keep_segments):
            filter_parts.append(
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];"
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];"
            )
            concat_inputs += f"[v{i}][a{i}]"
            
        filter_parts.append(
            f"{concat_inputs}concat=n={len(keep_segments)}:v=1:a=1[outv][outa]"
        )
        
        return "".join(filter_parts)


# Singleton
silence_remover = SilenceRemover()
