import sys
print("A - importing cv2", flush=True)
import cv2
print("B - cv2 OK", flush=True)
print("C - importing stream_capture", flush=True)
from services.stream_capture import stream_capture
print("D - stream_capture OK", flush=True)
