"""
Model Setup Script
──────────────────
Downloads required ML model weights for Vision AI, Audio AI, and Chat AI.

Usage:
    python scripts/setup_models.py              # Download all models
    python scripts/setup_models.py --vision     # Vision AI models only
    python scripts/setup_models.py --audio      # Audio AI models only
    python scripts/setup_models.py --chat       # Chat AI models only
    python scripts/setup_models.py --check      # Check what's installed
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models_store"
MODELS_DIR.mkdir(exist_ok=True)

# ── Model registry ───────────────────────────────────────────────

MODELS = {
    "vision": {
        "face_detector_caffe_model": {
            "url": "https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel",
            "filename": "res10_300x300_ssd_iter_140000.caffemodel",
            "size_mb": 10.4,
            "required": False,  # Falls back to Haar cascade
        },
        "face_detector_prototxt": {
            "url": "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt",
            "filename": "deploy.prototxt",
            "size_mb": 0.01,
            "required": False,
        },
        "haarcascade_frontalface": {
            "url": None,  # Ships with OpenCV; copy from cv2.data.haarcascades
            "filename": "haarcascade_frontalface_default.xml",
            "size_mb": 0.09,
            "required": False,
        },
    },
    "audio": {
        "wav2vec2_emotion": {
            "url": None,  # Auto-downloaded by HuggingFace transformers on first use
            "filename": "wav2vec2-emotion (HuggingFace cache)",
            "size_mb": 360.0,
            "required": False,
        },
    },
    "chat": {
        "nlp_sentiment_multilingual": {
            "url": None,  # Auto-downloaded by HuggingFace transformers on first use
            "filename": "sentiment-multilingual (HuggingFace cache)",
            "size_mb": 500.0,
            "required": False,
        },
    },
}


# ── Helpers ──────────────────────────────────────────────────────

def _download_file(url: str, dest: Path, desc: str = "") -> bool:
    """Download a file with progress indication."""
    label = desc or dest.name
    try:
        print(f"  Downloading {label}...", end="", flush=True)
        urllib.request.urlretrieve(url, str(dest))
        size_kb = dest.stat().st_size / 1024
        print(f" OK ({size_kb:.1f} KB)")
        return True
    except Exception as exc:
        print(f" FAILED: {exc}")
        return False


def _copy_haar_cascade() -> bool:
    """Copy the Haar cascade XML from OpenCV's bundled data."""
    try:
        import cv2
        src = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        dst = MODELS_DIR / "haarcascade_frontalface_default.xml"
        if dst.exists():
            print(f"  {dst.name} already exists, skipping")
            return True
        import shutil
        shutil.copy2(str(src), str(dst))
        print(f"  Copied {dst.name} from OpenCV ({dst.stat().st_size // 1024} KB)")
        return True
    except Exception as exc:
        print(f"  Haar cascade copy failed: {exc}")
        return False


# ── Main ─────────────────────────────────────────────────────────

def download_vision_models() -> None:
    print("\n[Vision AI Models]")
    for key, spec in MODELS["vision"].items():
        if key == "haarcascade_frontalface":
            _copy_haar_cascade()
            continue
        dest = MODELS_DIR / spec["filename"]
        if dest.exists():
            print(f"  {spec['filename']} already exists, skipping")
            continue
        if spec["url"]:
            _download_file(spec["url"], dest, spec["filename"])
        else:
            print(f"  {spec['filename']}: auto-download at runtime, skipping")


def download_audio_models() -> None:
    print("\n[Audio AI Models]")
    for key, spec in MODELS["audio"].items():
        print(f"  {spec['filename']}: auto-downloaded by HuggingFace on first use")


def download_chat_models() -> None:
    print("\n[Chat AI Models]")
    for key, spec in MODELS["chat"].items():
        print(f"  {spec['filename']}: auto-downloaded by HuggingFace on first use")


def check_installed() -> None:
    print("\n[Model Check]")
    for group, specs in MODELS.items():
        print(f"\n  {group.upper()} models:")
        for key, spec in specs.items():
            dest = MODELS_DIR / spec["filename"]
            exists = dest.exists() or "HuggingFace" in spec["filename"]
            status = "INSTALLED" if exists else "MISSING (will fallback)"
            print(f"    {spec['filename']:<45} {status}  (~{spec['size_mb']:.0f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Setup ML model weights")
    parser.add_argument("--vision", action="store_true", help="Download Vision AI models")
    parser.add_argument("--audio", action="store_true", help="Show Audio AI model info")
    parser.add_argument("--chat", action="store_true", help="Show Chat AI model info")
    parser.add_argument("--check", action="store_true", help="Check installed models")
    args = parser.parse_args()

    print("Tuncay-Klip Model Setup")
    print("=" * 40)
    print(f"Models directory: {MODELS_DIR}")

    if args.check:
        check_installed()
        return

    if not any([args.vision, args.audio, args.chat]):
        download_vision_models()
        download_audio_models()
        download_chat_models()
        check_installed()
        return

    if args.vision:
        download_vision_models()
    if args.audio:
        download_audio_models()
    if args.chat:
        download_chat_models()

    print("\nDone.")


if __name__ == "__main__":
    main()
