"""Atomic, revisioned timeline project persistence.

The project JSON format is the source of truth for editing state until the
video metadata store is promoted to PostgreSQL.  Each write is atomic and uses
an optimistic revision check so concurrent editors cannot silently overwrite
one another.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional
from uuid import uuid4

from services.timeline_engine import Timeline


class ProjectNotFoundError(KeyError):
    pass


class ProjectConflictError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Project:
    project_id: str
    name: str
    timeline: Timeline
    revision: int
    created_at: str
    updated_at: str
    schema_version: str = "1.0"

    @classmethod
    def create(
        cls,
        name: str,
        *,
        fps_numerator: int = 30,
        fps_denominator: int = 1,
        width: int = 1920,
        height: int = 1080,
    ) -> "Project":
        from fractions import Fraction

        now = _utc_now()
        return cls(
            project_id=str(uuid4()),
            name=name,
            timeline=Timeline.create(
                name=name,
                fps=Fraction(fps_numerator, fps_denominator),
                width=width,
                height=height,
            ),
            revision=1,
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "name": self.name,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "timeline": self.timeline.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Project":
        return cls(
            schema_version=data.get("schema_version", "1.0"),
            project_id=data["project_id"],
            name=data["name"],
            revision=data["revision"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            timeline=Timeline.from_dict(data["timeline"]),
        )


class ProjectStore:
    """Filesystem-backed store with per-process write serialization."""

    def __init__(self, root: Path = Path("data/projects")) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _path(self, project_id: str) -> Path:
        if not project_id or any(character not in "0123456789abcdef-" for character in project_id.lower()):
            raise ProjectNotFoundError(project_id)
        return self.root / f"{project_id}.json"

    def create(self, project: Project) -> Project:
        with self._lock:
            path = self._path(project.project_id)
            if path.exists():
                raise ProjectConflictError(f"Project already exists: {project.project_id}")
            self._atomic_write(path, project.to_dict())
        return project

    def get(self, project_id: str) -> Project:
        path = self._path(project_id)
        if not path.exists():
            raise ProjectNotFoundError(project_id)
        with path.open("r", encoding="utf-8") as handle:
            return Project.from_dict(json.load(handle))

    def list(self) -> List[Project]:
        projects: List[Project] = []
        for path in self.root.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    projects.append(Project.from_dict(json.load(handle)))
            except (OSError, ValueError, KeyError):
                # A corrupt project must not block all other projects from listing.
                continue
        return sorted(projects, key=lambda project: project.updated_at, reverse=True)

    def save(self, project: Project, expected_revision: Optional[int] = None) -> Project:
        with self._lock:
            path = self._path(project.project_id)
            if not path.exists():
                raise ProjectNotFoundError(project.project_id)
            current = self.get(project.project_id)
            required_revision = expected_revision if expected_revision is not None else project.revision
            if current.revision != required_revision:
                raise ProjectConflictError(
                    f"Project revision conflict: expected {required_revision}, current {current.revision}"
                )
            project.revision = current.revision + 1
            project.updated_at = _utc_now()
            self._atomic_write(path, project.to_dict())
        return project

    def delete(self, project_id: str) -> None:
        with self._lock:
            path = self._path(project_id)
            if not path.exists():
                raise ProjectNotFoundError(project_id)
            path.unlink()

    @staticmethod
    def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
        descriptor, temp_path = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
