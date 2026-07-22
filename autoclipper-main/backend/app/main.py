# backend/app/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from services.youtube import schedule_youtube_scan
from services.twitch import start_twitch_listener

app = FastAPI()

class ChannelConfig(BaseModel):
    source_platform: str      # "youtube" | "twitch" | "kick"
    source_id: str            # channel ID
    target_youtube_channel: str

@app.post("/config/")
async def configure(cfg: ChannelConfig):
    # save to DB (omitted)
    if cfg.source_platform == "youtube":
        schedule_youtube_scan(cfg.source_id)
    elif cfg.source_platform == "twitch":
        start_twitch_listener(cfg.source_id)
    return {"status": "configured"}

@app.post("/clip/{job_id}/retry")
async def retry_clip(job_id: str):
    # requeue a failed clip job
    from services.clipper import process_clip_job
    process_clip_job.delay(job_id)
    return {"status": "requeued"}
