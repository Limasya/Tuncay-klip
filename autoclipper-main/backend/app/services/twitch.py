# backend/app/services/twitch.py
import asyncio, time
from twitchio import Client
from .clipper import download_and_clip
from .subtitle import generate_srt
from .uploader import upload_clip

CHAT_COUNTS = []
BASELINE = 10   # messages per 30s (you’ll calibrate this)
THRESHOLD = 2.5

async def on_message(message):
    now = time.time()
    CHAT_COUNTS.append(now)
    # remove older than 30s
    while CHAT_COUNTS and CHAT_COUNTS[0] < now - 30:
        CHAT_COUNTS.pop(0)
    if len(CHAT_COUNTS) > BASELINE * THRESHOLD:
        # spike detected
        start = now - 15   # clip last 15s
        end   = now + 15   # plus next 15s
        # HLS URL: you’ll derive from channel name
        hls_url = f"https://twitch.tv/{CHANNEL_NAME}/live"
        clip_file = await download_and_clip(hls_url, start, end, f"clips/{CHANNEL_NAME}_{int(start)}.mp4")
        srt       = generate_srt(clip_file, clip_file.replace(".mp4", ".srt"))
        upload_clip(clip_file, title=f"Live highlight @ {int(start)}", description="Auto clipt from Twitch", channel_id=TARGET_CHANNEL)

def start_twitch_listener(channel_name, token):
    """Call this once after config to spin up the bot."""
    global CHANNEL_NAME, BASELINE
    CHANNEL_NAME = channel_name
    bot = Client(token=token, initial_channels=[channel_name])

    @bot.event()
    async def event_ready():
        print(f"Connected to Twitch chat for {channel_name}")

    bot.event(on_message)
    asyncio.ensure_future(bot.start())
