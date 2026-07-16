"""Persistent render-job records for timeline renders."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional
from uuid import uuid4

from services.project_store import Project


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TimelineRenderJob:
    job_id: str
    project_id: str
    project_revision: int
    project_snapshot: Dict[str, Any]
    render_config: Dict[str, Any]
    status: str
    created_at: str
    updated_at: str
    output_path: Optional[str] = None
    error: Optional[str] = None

    @classmethod
    def create(cls, project: Project, render_config: Dict[str, Any]) -> "TimelineRenderJob":
        now = _utc_now()
        return cls(
            job_id=str(uuid4()),
            project_id=project.project_id,
            project_revision=project.revision,
            project_snapshot=project.to_dict(),
            render_config=render_config,
            status="queued",
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()

    def public_dict(self) -> Dict[str, Any]:
        """Return the API representation without the internal project snapshot."""
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "project_revision": self.project_revision,
            "render_config": self.render_config,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "output_path": self.output_path,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimelineRenderJob":
        return cls(**data)


class TimelineRenderJobStore:
    def __init__(self, root: Path = Path("data/timeline-jobs")) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def create(self, job: TimelineRenderJob) -> TimelineRenderJob:
        with self._lock:
            self._write(job)
        return job

    def get(self, job_id: str) -> TimelineRenderJob:
        path = self.root / f"{job_id}.json"
        if not path.is_file():
            raise KeyError(job_id)
        with path.open("r", encoding="utf-8") as handle:
            return TimelineRenderJob.from_dict(json.load(handle))

    def update(self, job_id: str, **updates: Any) -> TimelineRenderJob:
        with self._lock:
            job = self.get(job_id)
            for key, value in updates.items():
                setattr(job, key, value)
            job.updated_at = _utc_now()
            self._write(job)
            return job

    def _write(self, job: TimelineRenderJob) -> None:
        path = self.root / f"{job.job_id}.json"
        descriptor, temp_path = tempfile.mkstemp(prefix=f".{job.job_id}.", suffix=".tmp", dir=str(self.root))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(job.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


timeline_render_jobs = TimelineRenderJobStore()
