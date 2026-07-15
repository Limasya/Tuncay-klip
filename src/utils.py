"""
Yardimci fonksiyonlar - src modulu.
"""
import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


def ensure_dir(path: str) -> Path:
    """Dizin varsa olusturur, Path dondurur."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_file_size_mb(path: str) -> float:
    """Dosya boyutunu MB cinsinden dondurur."""
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return 0.0


def format_duration(seconds: float) -> str:
    """Saniyeyi okunabilir formata cevirir (MM:SS veya HH:MM:SS)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_file_size(size_bytes: int) -> str:
    """Byte'i okunabilir formata cevirir."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def timestamp_to_filename(ts: Optional[datetime] = None) -> str:
    """Zaman damgasini dosya adi formatina cevirir."""
    if not ts:
        ts = datetime.now()
    return ts.strftime("%Y%m%d_%H%M%S")


def load_json(path: str) -> Optional[Dict]:
    """JSON dosyasi okur."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("JSON okuma hatasi (%s): %s", path, e)
        return None


def save_json(path: str, data: Any) -> bool:
    """JSON dosyasi yazar."""
    try:
        ensure_dir(str(Path(path).parent))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error("JSON yazma hatasi (%s): %s", path, e)
        return False


def clean_filename(name: str) -> str:
    """Dosya adindan gecersiz karakterleri temizler."""
    invalid_chars = '<>:"/\\|?*'
    for ch in invalid_chars:
        name = name.replace(ch, "_")
    return name.strip()
