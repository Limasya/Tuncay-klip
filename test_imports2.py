import sys
print("START", flush=True)

print("Importing numpy...", flush=True)
import numpy as np
print("numpy OK", flush=True)

print("Importing cv2...", flush=True)
import cv2
print("cv2 OK", flush=True)

print("Importing face_emotion...", flush=True)
from services.analysis.face_emotion import face_emotion_analyzer
print("face_emotion OK", flush=True)

print("Importing motion_detection...", flush=True)
from services.analysis.motion_detection import motion_analyzer
print("motion_detection OK", flush=True)

print("Importing audio_analysis...", flush=True)
from services.analysis.audio_analysis import audio_analyzer
print("audio_analysis OK", flush=True)

print("Importing pipeline...", flush=True)
from services.analysis.pipeline import analysis_pipeline
print("pipeline OK", flush=True)

print("Importing orchestrator...", flush=True)
from services.orchestrator import orchestrator
print("orchestrator OK", flush=True)

status = orchestrator.get_status()
print("STATUS:", status, flush=True)

print("ALL DONE", flush=True)
