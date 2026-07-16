"""Professional timeline/project editing API."""
from __future__ import annotations

import logging
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field, validator

from services.edit_spec import AspectRatio
from services.project_store import (
    Project,
    ProjectConflictError,
    ProjectNotFoundError,
    ProjectStore,
)
from services.render_pipeline import render_pipeline
from services.timeline_engine import EditMode, RationalTime, TimeRange, TimelineClip, TrackType
from services.timeline_jobs import TimelineRenderJob, timeline_render_jobs
from services.timeline_renderer import TimelineCompilationError, timeline_renderer


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/projects", tags=["projects", "timeline"])
project_store = ProjectStore()


class RationalTimeModel(BaseModel):
    numerator: int
    denominator: int = 1

    @validator("denominator")
    def denominator_must_not_be_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("denominator cannot be zero")
        return value

    def to_domain(self) -> RationalTime:
        return RationalTime(self.numerator, self.denominator)


class TimeRangeModel(BaseModel):
    start: RationalTimeModel
    duration: RationalTimeModel

    def to_domain(self) -> TimeRange:
        return TimeRange(self.start.to_domain(), self.duration.to_domain())


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    fps_numerator: int = Field(default=30, gt=0)
    fps_denominator: int = Field(default=1, gt=0)
    width: int = Field(default=1920, ge=16, le=16384)
    height: int = Field(default=1080, ge=16, le=16384)


class TrackCreateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    track_type: TrackType
    name: Optional[str] = Field(default=None, max_length=100)


class ClipCreateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    asset_path: str = Field(min_length=1)
    source_range: TimeRangeModel
    record_start: RationalTimeModel
    name: str = Field(default="", max_length=200)
    speed_numerator: int = Field(default=1, gt=0)
    speed_denominator: int = Field(default=1, gt=0)
    reverse: bool = False
    mode: EditMode = EditMode.INSERT
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RangeEditRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    time_range: TimeRangeModel
    mode: EditMode

    @validator("mode")
    def mode_must_remove(cls, value: EditMode) -> EditMode:
        if value not in (EditMode.LIFT, EditMode.EXTRACT):
            raise ValueError("range edit mode must be lift or extract")
        return value


class RippleTrimRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    new_source_duration: RationalTimeModel


class TimelineRenderRequest(BaseModel):
    aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE_16_9
    resolution: str = Field(default="1080p", max_length=30)
    crf: int = Field(default=20, ge=0, le=51)
    output_path: Optional[str] = None


def _project_or_404(project_id: str) -> Project:
    try:
        return project_store.get(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _save_project(project: Project, expected_revision: int) -> Project:
    try:
        return project_store.save(project, expected_revision=expected_revision)
    except ProjectConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("", status_code=201)
async def create_project(request: ProjectCreateRequest):
    project = Project.create(
        request.name,
        fps_numerator=request.fps_numerator,
        fps_denominator=request.fps_denominator,
        width=request.width,
        height=request.height,
    )
    return project_store.create(project).to_dict()


@router.get("")
async def list_projects(limit: int = Query(default=50, ge=1, le=200)):
    projects = project_store.list()[:limit]
    return {
        "projects": [
            {
                "project_id": project.project_id,
                "name": project.name,
                "revision": project.revision,
                "updated_at": project.updated_at,
                "duration": project.timeline.duration.to_dict(),
                "track_count": len(project.timeline.tracks),
            }
            for project in projects
        ],
        "total": len(projects),
    }


@router.get("/{project_id}")
async def get_project(project_id: str):
    return _project_or_404(project_id).to_dict()


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str):
    try:
        project_store.delete(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("/{project_id}/tracks")
async def add_track(project_id: str, request: TrackCreateRequest):
    project = _project_or_404(project_id)
    project.timeline.add_track(request.track_type, request.name)
    return _save_project(project, request.expected_revision).to_dict()


@router.post("/{project_id}/tracks/{track_id}/clips")
async def add_clip(project_id: str, track_id: str, request: ClipCreateRequest):
    project = _project_or_404(project_id)
    try:
        track = project.timeline.get_track(track_id)
        clip = TimelineClip.create(
            asset_path=request.asset_path,
            source_range=request.source_range.to_domain(),
            record_start=request.record_start.to_domain(),
            name=request.name,
            speed=Fraction(request.speed_numerator, request.speed_denominator),
            reverse=request.reverse,
            metadata=request.metadata,
        )
        track.insert_clip(clip, request.record_start.to_domain(), request.mode)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=423, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    saved = _save_project(project, request.expected_revision)
    return {"project": saved.to_dict(), "clip_id": clip.clip_id}


@router.post("/{project_id}/tracks/{track_id}/range-edit")
async def range_edit(project_id: str, track_id: str, request: RangeEditRequest):
    project = _project_or_404(project_id)
    try:
        project.timeline.get_track(track_id).remove(request.time_range.to_domain(), request.mode)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=423, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _save_project(project, request.expected_revision).to_dict()


@router.post("/{project_id}/tracks/{track_id}/clips/{clip_id}/ripple-trim")
async def ripple_trim(
    project_id: str,
    track_id: str,
    clip_id: str,
    request: RippleTrimRequest,
):
    project = _project_or_404(project_id)
    try:
        project.timeline.get_track(track_id).ripple_trim(
            clip_id, request.new_source_duration.to_domain()
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=423, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _save_project(project, request.expected_revision).to_dict()


@router.post("/{project_id}/renders", status_code=202)
async def render_project(
    project_id: str,
    request: TimelineRenderRequest,
    background_tasks: BackgroundTasks,
):
    project = _project_or_404(project_id)
    render_config = {
        "aspect_ratio": request.aspect_ratio.value,
        "resolution": request.resolution,
        "crf": request.crf,
        "output_path": request.output_path,
    }
    job = TimelineRenderJob.create(project, render_config)
    exports_root = Path("data/exports").resolve()
    output_path = Path(request.output_path).resolve() if request.output_path else (
        exports_root / f"timeline_{project.project_id}_{job.job_id[:8]}.mp4"
    )
    try:
        output_path.relative_to(exports_root)
    except ValueError:
        raise HTTPException(status_code=422, detail="output_path must be inside data/exports")
    if output_path.suffix.lower() != ".mp4":
        raise HTTPException(status_code=422, detail="Timeline render output must use .mp4")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path = str(output_path)
    job.render_config["output_path"] = output_path
    try:
        timeline_renderer.compile(
            project,
            output_path=output_path,
            aspect_ratio=request.aspect_ratio,
            resolution=request.resolution,
            crf=request.crf,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"Asset not found: {exc}")
    except TimelineCompilationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    timeline_render_jobs.create(job)
    background_tasks.add_task(_execute_timeline_render, job.job_id)
    return job.public_dict()


@router.get("/renders/{job_id}")
async def get_render_job(job_id: str):
    try:
        return timeline_render_jobs.get(job_id).public_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail="Render job not found")


async def _execute_timeline_render(job_id: str) -> None:
    try:
        job = timeline_render_jobs.update(job_id, status="rendering", error=None)
        project = Project.from_dict(job.project_snapshot)
        config = job.render_config
        plan = timeline_renderer.compile(
            project,
            output_path=config["output_path"],
            aspect_ratio=AspectRatio(config["aspect_ratio"]),
            resolution=config["resolution"],
            crf=config["crf"],
        )
        result = await render_pipeline.render_montage(plan.montage)
        if not result:
            raise RuntimeError("Timeline render returned no output")
        timeline_render_jobs.update(
            job_id,
            status="completed",
            output_path=result,
            error=None,
        )
    except Exception as exc:
        logger.exception("Timeline render job failed: %s", job_id)
        timeline_render_jobs.update(job_id, status="failed", error=str(exc))
