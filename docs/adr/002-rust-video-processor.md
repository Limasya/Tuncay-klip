# ADR-002: Use Rust for VOD Processing CLI

## Status
Accepted

## Context
VOD processing (clipping, probing, validating, exporting, checksumming) is I/O-bound and benefits from a compiled language for reliability and speed. The CLI tool is invoked by Python as a subprocess and must handle large video files (5-50GB) without memory issues.

Go was considered but adds a runtime dependency. Python alternatives are slow for large files. C++ would work but has memory safety concerns for I/O-heavy code.

## Decision
Implement a Rust binary (`tuncay-video-processor`) that exposes a subprocess CLI with commands: `clip`, `probe`, `validate`, `export`, `batch`, `checksum`, `version`. Python wraps it via `shared/utils/video_processor.py` with FFmpeg fallback if binary is unavailable.

## Consequences
- **Positive**: Memory-safe I/O handling with zero-copy where possible.
- **Positive**: Single static binary per platform — no runtime dependencies beyond FFmpeg.
- **Positive**: All crates are MIT/Apache-2.0 licensed — zero copyleft risk.
- **Negative**: Subprocess invocation adds ~50ms startup overhead per call (mitigated by FFmpeg fallback for simple operations).
- **Negative**: Requires Rust toolchain for development builds.
- **Mitigation**: `build.ps1` handles cargo build. CI caches Rust artifacts.
