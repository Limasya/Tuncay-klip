# backend/app/services/youtube.py
import os
from googleapiclient.discovery import build
from celery_app import celery
from .clipper import download_and_clip
from .uploader import upload_clip
from datetime import datetime

API_KEY = os.getenv("YOUTUBE_API_KEY")
YT = build("youtube", "v3", developerKey=API_KEY)

CHANNEL_ID = None  # will be passed in

def list_recent_videos(channel_id, days=1):
    """Return video IDs uploaded in the last `days` days."""
    published_after = (datetime.utcnow() - timedelta(days=days)).isoformat("T") + "Z"
    res = (
        YT.search()
        .list(channelId=channel_id, part="id", order="date", publishedAfter=published_after, maxResults=50)
        .execute()
    )
    return [item["id"]["videoId"] for item in res.get("items", []) if item["id"]["kind"] == "youtube#video"]

def get_retention_peaks(video_id, threshold=1.5):
    """
    Call the Analytics API to get relative audience retention by second,
    pick points > threshold × average.
    """
    # build with Analytics API v2
    analytics = build("youtubeAnalytics", "v2", developerKey=API_KEY)
    data = analytics.reports().query(
        ids=f"channel=={CHANNEL_ID}",
        metrics="relativeRetentionPerformance",
        dimensions="elapsedVideoTimeRatio",
        filters=f"video=={video_id}"
    ).execute()
    # parse ratios into time windows...
    # here you’d map the ratio peaks back to actual seconds and return [(start, end), ...]
    # For brevity, pretend we detect one peak:
    return [(30, 45)]

def get_comment_timestamps(video_id):
    """
    Parse comments looking for mm:ss patterns, count frequencies,
    return top-N windows.
    """
    times = {}
    tube = build("youtube", "v3", developerKey=API_KEY)
    req = tube.commentThreads().list(videoId=video_id, part="snippet", maxResults=100).execute()
    for item in req.get("items", []):
        text = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
        for match in re.findall(r"(\d+):(\d{2})", text):
            sec = int(match[0]) * 60 + int(match[1])
            times[sec] = times.get(sec, 0) + 1
    # pick top 3 timestamps
    top = sorted(times.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return [(t-5, t+10) for (t, _) in top]  # 5s before to 10s after

@celery.task(name="services.youtube.scan_channel")
def scan_channel(channel_id):
    global CHANNEL_ID
    CHANNEL_ID = channel_id
    videos = list_recent_videos(channel_id)
    for vid in videos:
        # merge retention peaks + comment windows
        windows = get_retention_peaks(vid) + get_comment_timestamps(vid)
        for start, end in windows:
            # enqueue clip → subtitle → upload chain
            job = download_and_clip(f"https://youtu.be/{vid}", start, end, f"clips/{vid}_{start}.mp4")
            srt   = generate_srt(job, job.replace(".mp4", ".srt"))
            upload_clip(job, title=f"Highlight: {vid} @ {start}s", description="Auto-clipped by Bot", channel_id=TARGET_CHANNEL)
