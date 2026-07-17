"""
VOD İndirme Servisi (yt-dlp Entegrasyonu)
─────────────────────────────────────────
YouTube, Twitch veya Kick linklerinden videoyu indirip,
kurgu (master_pipeline) için sisteme hazırlar.
"""
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

logger = logging.getLogger("youtube_downloader")

class YouTubeDownloader:
    def __init__(self):
        self.download_dir = Path("data/raw_vods")
        self.download_dir.mkdir(parents=True, exist_ok=True)

    async def download_video(self, url: str) -> Dict[str, Any]:
        """Verilen URL'den videoyu 1080p kalitesinde indirir."""
        if not yt_dlp:
            return {"error": "yt-dlp is not installed"}

        logger.info(f"Starting VOD download for {url}")
        
        # CPU blocking islemi (indirme) thread'de calistir
        return await asyncio.to_thread(self._run_yt_dlp, url)

    def _run_yt_dlp(self, url: str) -> Dict[str, Any]:
        output_template = str(self.download_dir / "%(title)s_%(id)s.%(ext)s")
        
        # Sadece en iyi 1080p videoyu ve en iyi sesi al, mp4 formatinda birlestir
        ydl_opts = {
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_template,
            'merge_output_format': 'mp4',
            'quiet': False,
            'no_warnings': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                file_path = ydl.prepare_filename(info_dict)
                
                # Birlestirme islemi yuzunden bazen uzanti degisebilir, kontrol edelim
                path_obj = Path(file_path)
                if not path_obj.exists():
                    # Mkv vs yapildiysa onu bulalim
                    possible_paths = list(self.download_dir.glob(f"{path_obj.stem}.*"))
                    if possible_paths:
                        file_path = str(possible_paths[0])
                        
                return {
                    "success": True,
                    "title": info_dict.get("title", "Unknown"),
                    "file_path": file_path,
                    "duration": info_dict.get("duration", 0)
                }
        except Exception as e:
            logger.error("Download failed: %s", str(e))
            return {"error": str(e)}

# Singleton
youtube_downloader = YouTubeDownloader()
