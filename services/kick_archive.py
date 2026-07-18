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
        pipeline_config=None,
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
                        config=pipeline_config,
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

    async def _run_sync_task(self, vod_limit: int | None, max_clips_per_vod: int | None, pipeline_config=None) -> None:
        try:
            self._last_report = await self.sync_archive(vod_limit, max_clips_per_vod, pipeline_config=pipeline_config)
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
        pipeline_config=None,
    ) -> dict[str, Any]:
        """Start one archive pass in the background without accepting a URL."""
        if self._sync_lock.locked() or (self._active_task and not self._active_task.done()):
            return {
                "status": "already_running",
                "channel": TARGET_CHANNEL_SLUG,
                "channel_url": TARGET_CHANNEL_URL,
            }
        self._active_task = asyncio.create_task(
            self._run_sync_task(vod_limit, max_clips_per_vod, pipeline_config=pipeline_config),
            name="kick-archive-sync",
        )
        return {
            "status": "accepted",
            "channel": TARGET_CHANNEL_SLUG,
            "channel_url": TARGET_CHANNEL_URL,
        }

    # ─── Zero-Bandwidth Periyodik Tarama ───────────────────────────────────

    async def _run_zero_bandwidth_scan(self) -> None:
        """Periyodik zero-bandwidth tarama: sadece metadata + LLM tahmini."""
        settings = get_settings()
        state = await self._read_state()
        zw_state = state.get("zero_bandwidth_analyses", {})

        try:
            from services.zero_bandwidth_clipper import ZeroBandwidthClipper
            clipper = ZeroBandwidthClipper()

            vods = await self.list_public_vods(settings.kick_archive_vod_limit)
            new_count = 0
            skipped_count = 0

            for vod in vods:
                vod_id = str(vod.get("vod_id", ""))
                vod_url = str(vod.get("url", ""))

                if not vod_id or not vod_url:
                    continue

                # Daha once analiz edilmis mi?
                existing = zw_state.get(vod_id, {})
                if existing.get("status") == "completed":
                    skipped_count += 1
                    continue

                # Analiz et (sadece KB, sifir indirme)
                try:
                    analysis = await clipper.analyze_vod(vod_url)

                    # Sonuclari state'e yaz (kalici depolama)
                    zw_state[vod_id] = {
                        "status": "completed",
                        "vod_id": vod_id,
                        "vod_url": vod_url,
                        "title": analysis.title,
                        "duration": analysis.duration,
                        "category": analysis.category,
                        "total_clips": len(analysis.clips),
                        "clips": [
                            {
                                "clip_id": c.clip_id,
                                "title": c.title,
                                "start_time": c.start_time,
                                "end_time": c.end_time,
                                "duration": c.duration,
                                "confidence": c.confidence,
                                "source": c.source,
                                "reason": c.reason,
                            }
                            for c in analysis.clips
                        ],
                        "bandwidth_used_kb": analysis.bandwidth_used_kb,
                        "analysis_time_sec": analysis.analysis_time_sec,
                        "analyzed_at": self._timestamp(),
                    }
                    new_count += 1
                    logger.info(
                        "Zero-bandwidth analiz: %s — %d clip (%.1f KB, %.1fs)",
                        analysis.title[:30], len(analysis.clips),
                        analysis.bandwidth_used_kb, analysis.analysis_time_sec,
                    )

                except Exception as exc:
                    zw_state[vod_id] = {
                        "status": "failed",
                        "vod_id": vod_id,
                        "error": str(exc),
                        "failed_at": self._timestamp(),
                    }
                    logger.warning("Zero-bandwidth analiz basarisiz %s: %s", vod_id, exc)

            # State'i kaydet
            state["zero_bandwidth_analyses"] = zw_state
            await self._write_state(state)

            logger.info(
                "Zero-bandwidth tarama tamamlandi: %d yeni, %d atlandi",
                new_count, skipped_count,
            )

        except Exception as exc:
            logger.exception("Zero-bandwidth tarama hatasi")

    async def _zero_bandwidth_scheduler_loop(self) -> None:
        """Zero-bandwidth icin ayri scheduler dongusu."""
        settings = get_settings()
        interval_seconds = max(120, int(settings.zero_bandwidth_scan_interval_minutes) * 60)
        logger.info(
            "Zero-bandwidth scheduler baslatildi: %d dakika aralikla",
            settings.zero_bandwidth_scan_interval_minutes,
        )
        while True:
            await self._run_zero_bandwidth_scan()
            await asyncio.sleep(interval_seconds)

    async def start_zero_bandwidth_scheduler(self) -> bool:
        """Zero-bandwidth periyodik taramasini baslat."""
        if self._scheduler_task and not self._scheduler_task.done():
            return False
        self._scheduler_task = asyncio.create_task(
            self._zero_bandwidth_scheduler_loop(),
            name="zero-bandwidth-scheduler",
        )
        return True

    def start_zero_bandwidth_sync(self) -> dict[str, Any]:
        """Tek seferlik zero-bandwidth analiz baslat."""
        if self._sync_lock.locked() or (self._active_task and not self._active_task.done()):
            return {"status": "already_running"}
        self._active_task = asyncio.create_task(
            self._run_zero_bandwidth_scan(),
            name="zero-bandwidth-one-shot",
        )
        return {"status": "accepted"}

    async def get_zero_bandwidth_status(self) -> dict[str, Any]:
        """Zero-bandwidth analiz durumunu dondur."""
        state = await self._read_state()
        zw = state.get("zero_bandwidth_analyses", {})
        counts = {"completed": 0, "failed": 0}
        total_clips = 0
        for item in zw.values():
            s = item.get("status")
            if s in counts:
                counts[s] += 1
            total_clips += int(item.get("total_clips", 0))
        return {
            "analyses": counts,
            "total_clips": total_clips,
            "total_vods": len(zw),
            "scheduler_running": bool(self._scheduler_task and not self._scheduler_task.done()),
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
