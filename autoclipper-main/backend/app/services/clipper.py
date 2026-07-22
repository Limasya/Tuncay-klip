# backend/app/services/clipper.py
import ffmpeg, yt_dlp, os

def download_and_clip(url: str, start: float, end: float, out_path: str):
    """Downloads a segment [start,end] and outputs out_path."""
    ydl_opts = {
        "format": "bestvideo+bestaudio",
        "outtmpl": "tmp/%(id)s.%(ext)s",
        "download_sections": {"highlight": [{"start_time": start, "end_time": end}]}
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        src = ydl.prepare_filename(info)
    (
      ffmpeg
      .input(src, ss=start, to=end)
      .output(out_path, vcodec="libx264", acodec="aac")
      .run(overwrite_output=True)
    )
    return out_path
