# ADR-004: Delete Go Render Engine (Dead Code Removal)

## Status
Accepted

## Context
A Go render engine (`render_engine/main.go`) was previously part of the polyglot architecture, providing FFmpeg trim+scale operations via a goroutine worker pool. An audit revealed:
- The Go render engine is **dead code** — `RenderEngineClient` in `microservices_client.py` exists but is never imported or called by any other Python module.
- The Go engine is a stripped-down subset of Python's `render_pipeline.py` — it only does trim+scale, while Python handles subtitles, effects, beat-sync, stickers, quality checks, and multi-platform optimization.
- No unique capability exists in the Go version.

## Decision
Delete the entire `render_engine/` directory and remove all references:
- Remove `RenderEngineClient` class and `render_engine` singleton from `microservices_client.py`
- Remove `RENDER_ENGINE_URL` environment variable
- Remove `render-engine` CI job from `.github/workflows/ci.yml`
- Update `POLYGLOT_README.md` to remove Go Render Engine from services table and architecture diagram

## Consequences
- **Positive**: Eliminates maintenance burden of an unused service.
- **Positive**: Simplifies the architecture diagram and deployment.
- **Positive**: Removes a build dependency (Go toolchain) from CI and local development.
- **Positive**: One fewer port to manage (3002 removed).
- **Negative**: Loss of a theoretical "simple clip rendering" microservice, but Python's render pipeline handles this with far more features.
- **Mitigation**: If lightweight concurrent FFmpeg rendering is needed in the future, Python's `asyncio.create_subprocess_exec` with semaphore-based concurrency (already used in `render_pipeline.py`) is sufficient.
