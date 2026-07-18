import asyncio
import sys
from services.youtube_downloader import youtube_downloader, _FFMPEG_PATH

print("FFMPEG_PATH:", _FFMPEG_PATH)
strategies = youtube_downloader.get_strategies()
for s in strategies:
    print(f"  {s['name']}: available={s['available']}, enabled={s['enabled']}")

print("\nTesting download of first VOD...")
sys.stdout.flush()

async def test():
    url = "https://kick.com/thetuncay/videos/3a334756-gec-oslun-guc-olmasun-dc-ig"
    result = await youtube_downloader.download_video(url)
    if result.get("success"):
        print(f"SUCCESS: {result.get('file_path')}")
        import os
        size_mb = os.path.getsize(result["file_path"]) / (1024 * 1024)
        print(f"Size: {size_mb:.1f} MB")
    else:
        print(f"FAILED: {result.get('error')}")
    sys.stdout.flush()

asyncio.run(test())
