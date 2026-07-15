import sys
print("1. START", flush=True)

print("2. config...", flush=True)
from config import get_settings

print("3. kick_api...", flush=True)
from services.kick_api import kick_service

print("4. stream_capture...", flush=True)
from services.stream_capture import stream_capture

print("5. face_emotion...", flush=True)
from services.analysis.face_emotion import face_emotion_analyzer

print("6. motion_detection...", flush=True)
from services.analysis.motion_detection import motion_analyzer

print("7. audio_analysis...", flush=True)
from services.analysis.audio_analysis import audio_analyzer

print("8. analysis pipeline...", flush=True)
from services.analysis.pipeline import analysis_pipeline

print("9. clip_service...", flush=True)
from services.clip_service import clip_classifier, clip_metadata, storage_service

print("10. subtitle_service...", flush=True)
from services.subtitle_service import subtitle_service

print("11. video_editor...", flush=True)
from services.video_editor import video_editor

print("12. chat_sentiment...", flush=True)
from services.chat_sentiment import chat_sentiment

print("13. orchestrator...", flush=True)
from services.orchestrator import orchestrator

print("14. get_status...", flush=True)
status = orchestrator.get_status()
print("STATUS:", status, flush=True)

print("ALL DONE", flush=True)
