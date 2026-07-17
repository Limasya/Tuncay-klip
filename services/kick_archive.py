"""Public VOD archive processing for the fixed ``kick.com/thetuncay`` channel.

The service discovers public VOD metadata from Kick, processes each VOD through
the existing master pipeline, and persists per-VOD state locally. It never
accepts a channel slug or arbitrary source URL from an API caller.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING
from urllib.parse import urlparse

from config import get_settings
from services.kick_api import kick_service

if TYPE_CHECKING:
    from services.kick_api import KickAPIService
    from services.master_pipeline import MasterPipeline


logger = logging.getLogger("kick_archive")
TARGET_CHANNEL_SLUG = "thetuncay"
TARGET_CHANNEL_URL = f"https://kick.com/{TARGET_CHANNEL_SLUG}"


def is_target_channel_url(url: str) -> bool:
    """Return whether a URL identifies the fixed public Kick channel."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"kick.com", "www.kick.com"}:
        return False
    return [part.lower() for part in parsed.path.split("/") if part] == [TARGET_CHANNEL_SLUG]


def is_target_vod_url(url: str) -> bool:
    """Return whether a URL is a public VOD page belonging to the target channel."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"kick.com", "www.kick.com"}:
        return False
    parts = [part.lower() for part in parsed.path.split("/") if part]
    return len(parts) >= 3 and parts[0] == TARGET_CHANNEL_SLUG and parts[1] == "videos"


class KickArchiveService:
    """Discover and process public VODs for the fixed target channel."""

    def __init__(
        self,
        kick_client: KickAPIService | None = None,
        pipeline: MasterPipeline | None = None,
        state_path: str | Path | None = None,
    ) -> None:
        settings = get_settings()
        self._kick_client = kick_client or kick_service
        self._pipeline = pipeline
        self._state_path = Path(state_path or settings.kick_archive_state_file)
        self._sync_lock = asyncio.Lock()
        self._active_task: asyncio.Task | None = None
        self._scheduler_task: asyncio.Task | None = None
        self._last_report: dict[str, Any] | None = None

    @property
    def pipeline(self) -> MasterPipeline:
        if self._pipeline is None:
            from services.master_pipeline import master_pipeline
            self._pipeline = master_pipeline
        return self._pipeline

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _default_state(self) -> dict[str, Any]:
        return {
            "channel": TARGET_CHANNEL_SLUG,
            "updated_at": self._timestamp(),
            "vods": {},
        }

    def _read_state_sync(self) -> dict[str, Any]:
        if not self._state_path.exists():
            return self._default_state()
        try:
            state = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Archive state could not be read: %s", exc)
            return self._default_state()
        if not isinstance(state, dict) or state.get("channel") != TARGET_CHANNEL_SLUG:
            return self._default_state()
        if not isinstance(state.get("vods"), dict):
            state["vods"] = {}
        return state

    def _write_state_sync(self, state: dict[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = self._timestamp()
        temp_path = self._state_path.with_suffix(f"{self._state_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temp_path.replace(self._state_path)

    async def _read_state(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._read_state_sync)

    async def _write_state(self, state: dict[str, Any]) -> None:
        await asyncio.to_thread(self._write_state_sync, state)

    async def list_public_vods(self, limit: int) -> list[dict[str, Any]]:
        """Fetch public VOD metadata and reject unexpected source URLs."""
        vods = await self._kick_client.list_public_vods(limit)
        accepted: list[dict[str, Any]] = []
        for vod in vods:
            url = str(vod.get("url") or "")
            if not is_target_vod_url(url):
                logger.warning("Ignoring untrusted VOD URL: %s", url)
                continue
            accepted.append(vod)
        return accepted

    async def sync_archive(
        self,
        vod_limit: int | None = None,
        max_clips_per_vod: int | None = None,
    ) -> dict[str, Any]:
        """Process unprocessed public VODs, one at a time, with deduplication."""
        settings = get_settings()
        vod_limit = vod_limit or settings.kick_archive_vod_limit
        max_clips_per_vod = max_clips_per_vod or settings.kick_archive_max_clips_per_vod
        vod_limit = max(1, min(int(vod_limit), 50))
        max_clips_per_vod = max(1, min(int(max_clips_per_vod), 10))

        if self._sync_lock.locked():
            return {
                "status": "already_running",
                "channel": TARGET_CHANNEL_SLUG,
                "channel_url": TARGET_CHANNEL_URL,
            }

        async with self._sync_lock:
            report: dict[str, Any] = {
                "status": "completed",
                "channel": TARGET_CHANNEL_SLUG,
                "channel_url": TARGET_CHANNEL_URL,
                "vod_limit": vod_limit,
                "max_clips_per_vod": max_clips_per_vod,
                "discovered": 0,
                "processed": 0,
                "skipped": 0,
                "failed": 0,
                "clips_generated": 0,
                "vods": [],
            }
            state = await self._read_state()
            vods = await self.list_public_vods(vod_limit)
            report["discovered"] = len(vods)

            for vod in vods:
                vod_id = str(vod.get("vod_id"))
                existing = state["vods"].get(vod_id, {})
                if existing.get("status") == "completed":
                    report["skipped"] += 1
                    report["vods"].append({"vod_id": vod_id, "status": "skipped"})
                    continue

                state["vods"][vod_id] = {
                    **existing,
                    **vod,
                    "status": "processing",
                    "started_at": self._timestamp(),
                    "error": "",
                }
                await self._write_state(state)

                try:
                    result = await self.pipeline.process_url(
                        vod["url"],
                        max_clips=max_clips_per_vod,
                        game=str(vod.get("category") or "Kick"),
                        streamer="Tuncay",
                    )
                except Exception as exc:  # pragma: no cover - defensive task boundary
                    logger.exception("VOD processing crashed for %s", vod_id)
                    result = {"success": False, "error": str(exc)}

                if result.get("success"):
                    clips_generated = int(result.get("total_clips", 0))
                    state["vods"][vod_id].update({
                        "status": "completed",
                        "completed_at": self._timestamp(),
                        "clips_generated": clips_generated,
                        "error": "",
                    })
                    report["processed"] += 1
                    report["clips_generated"] += clips_generated
                    report["vods"].append({
                        "vod_id": vod_id,
                        "status": "completed",
                        "clips_generated": clips_generated,
                    })
                else:
                    error = str(result.get("error") or "Pipeline failed")
                    state["vods"][vod_id].update({
                        "status": "failed",
                        "failed_at": self._timestamp(),
                        "error": error,
                    })
                    report["failed"] += 1
                    report["vods"].append({"vod_id": vod_id, "status": "failed", "error": error})
                await self._write_state(state)

            self._last_report = report
            return report

    async def _run_sync_task(self, vod_limit: int | None, max_clips_per_vod: int | None) -> None:
        try:
            self._last_report = await self.sync_archive(vod_limit, max_clips_per_vod)
        except Exception as exc:  # pragma: no cover - defensive task boundary
            logger.exception("Kick archive task failed")
            self._last_report = {
                "status": "failed",
                "channel": TARGET_CHANNEL_SLUG,
                "error": str(exc),
            }

    def start_sync(
        self,
        vod_limit: int | None = None,
        max_clips_per_vod: int | None = None,
    ) -> dict[str, Any]:
        """Start one archive pass in the background without accepting a URL."""
        if self._sync_lock.locked() or (self._active_task and not self._active_task.done()):
            return {
                "status": "already_running",
                "channel": TARGET_CHANNEL_SLUG,
                "channel_url": TARGET_CHANNEL_URL,
            }
        self._active_task = asyncio.create_task(
            self._run_sync_task(vod_limit, max_clips_per_vod),
            name="kick-archive-sync",
        )
        return {
            "status": "accepted",
            "channel": TARGET_CHANNEL_SLUG,
            "channel_url": TARGET_CHANNEL_URL,
        }

    async def _scheduler_loop(self) -> None:
        settings = get_settings()
        interval_seconds = max(60, int(settings.kick_archive_interval_minutes) * 60)
        while True:
            await self._run_sync_task(None, None)
            await asyncio.sleep(interval_seconds)

    async def start_scheduler(self) -> bool:
        """Start periodic archive discovery if it is not already active."""
        if self._scheduler_task and not self._scheduler_task.done():
            return False
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(), name="kick-archive-scheduler",
        )
        logger.info("Kick archive scheduler started for %s", TARGET_CHANNEL_URL)
        return True

    async def stop(self) -> None:
        """Stop any scheduled or manually started archive processing."""
        tasks = [task for task in (self._scheduler_task, self._active_task) if task and not task.done()]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._scheduler_task = None
        self._active_task = None

    async def get_status(self) -> dict[str, Any]:
        """Return safe operational state for the fixed target archive."""
        state = await self._read_state()
        vods = state.get("vods", {})
        counts = {"completed": 0, "processing": 0, "failed": 0}
        for item in vods.values():
            status = item.get("status")
            if status in counts:
                counts[status] += 1
        return {
            "channel": TARGET_CHANNEL_SLUG,
            "channel_url": TARGET_CHANNEL_URL,
            "running": self._sync_lock.locked() or bool(self._active_task and not self._active_task.done()),
            "scheduler_running": bool(self._scheduler_task and not self._scheduler_task.done()),
            "state_file": str(self._state_path),
            "vod_counts": counts,
            "last_report": self._last_report,
            "updated_at": state.get("updated_at"),
        }


kick_archive = KickArchiveService()
