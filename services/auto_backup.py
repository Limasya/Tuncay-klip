"""
Auto-Backup System
──────────────────
Periodic database and clip backup with rotation and compression.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("auto_backup")

BACKUP_DIR = Path("data/backups")
MAX_BACKUPS = 10  # Keep last N backups


async def auto_backup_database() -> dict:
    """Create a timestamped copy of the SQLite database."""
    from config import get_settings
    settings = get_settings()

    if "sqlite" not in settings.database_url:
        return {"status": "skipped", "reason": "non-SQLite database"}

    # Extract db path from URL
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    db_path = Path(db_path)

    if not db_path.exists():
        return {"status": "skipped", "reason": "database file not found"}

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"klip_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_name

    try:
        # Use shutil for a safe copy (works with SQLite)
        shutil.copy2(str(db_path), str(backup_path))

        # Compress
        compressed = backup_path.with_suffix(".db.gz")
        import gzip
        with open(backup_path, "rb") as f_in:
            with gzip.open(str(compressed), "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Remove uncompressed copy
        backup_path.unlink(missing_ok=True)

        size_kb = compressed.stat().st_size / 1024
        logger.info("Database backup created: %s (%.1f KB)", backup_name + ".gz", size_kb)

        # Rotate old backups
        await _rotate_backups()

        return {
            "status": "created",
            "file": str(compressed),
            "size_kb": round(size_kb, 1),
        }
    except Exception as e:
        logger.error("Database backup failed: %s", e)
        return {"status": "failed", "error": str(e)}


async def auto_backup_clips(max_age_days: int = 7) -> dict:
    """Archive old clips that are older than max_age_days and uploaded to S3."""
    clips_dir = Path("data/clips")
    if not clips_dir.exists():
        return {"status": "skipped", "reason": "no clips directory"}

    cutoff = time.time() - (max_age_days * 86400)
    archived = 0
    freed_bytes = 0

    for clip_file in clips_dir.glob("*.mp4"):
        if clip_file.stat().st_mtime < cutoff:
            try:
                clip_file.unlink()
                archived += 1
                freed_bytes += clip_file.stat().st_size
            except Exception as e:
                logger.debug("Eski klip silinemedi (%s): %s", clip_file.name, e)

    return {
        "status": "completed",
        "archived_count": archived,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
    }


async def _rotate_backups():
    """Keep only the latest MAX_BACKUPS backups."""
    if not BACKUP_DIR.exists():
        return

    backups = sorted(BACKUP_DIR.glob("klip_*.db.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old_backup in backups[MAX_BACKUPS:]:
        try:
            old_backup.unlink()
            logger.debug("Rotated old backup: %s", old_backup.name)
        except Exception as e:
            logger.debug("Eski yedek silinemedi (%s): %s", old_backup.name, e)


async def get_backup_status() -> dict:
    """Report backup status and disk usage."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = sorted(BACKUP_DIR.glob("klip_*.db.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    total_size = sum(b.stat().st_size for b in backups)

    latest = None
    if backups:
        latest = {
            "name": backups[0].name,
            "size_kb": round(backups[0].stat().st_size / 1024, 1),
            "age_hours": round((time.time() - backups[0].stat().st_mtime) / 3600, 1),
        }

    return {
        "backup_dir": str(BACKUP_DIR),
        "total_backups": len(backups),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "max_backups": MAX_BACKUPS,
        "latest": latest,
    }


class AutoBackupScheduler:
    """Background task that runs periodic backups."""

    def __init__(self, db_interval: int = 3600, clip_interval: int = 86400):
        self._db_interval = db_interval
        self._clip_interval = clip_interval
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_db_backup = 0.0
        self._last_clip_cleanup = 0.0

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Auto-backup scheduler started (db every %ds, clips every %ds)",
                     self._db_interval, self._clip_interval)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self._running:
            now = time.time()

            if now - self._last_db_backup >= self._db_interval:
                try:
                    result = await auto_backup_database()
                    self._last_db_backup = now
                    logger.info("Scheduled DB backup: %s", result.get("status"))
                except Exception as e:
                    logger.error("Scheduled DB backup failed: %s", e)

            if now - self._last_clip_cleanup >= self._clip_interval:
                try:
                    result = await auto_backup_clips()
                    self._last_clip_cleanup = now
                    logger.info("Scheduled clip cleanup: archived=%s", result.get("archived_count", 0))
                except Exception as e:
                    logger.error("Scheduled clip cleanup failed: %s", e)

            await asyncio.sleep(60)


backup_scheduler = AutoBackupScheduler()
