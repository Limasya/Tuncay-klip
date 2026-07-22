# backend/app/services/subtitle.py
import whisper

model = whisper.load_model("base")
def generate_srt(video_path: str, srt_path: str):
    result = model.transcribe(video_path, verbose=False)
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(whisper.utils.write_srt(result["segments"]))
    return srt_path
