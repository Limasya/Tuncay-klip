# Tuncay Klip — Project Overview

## Architecture
- **Python monolith** (FastAPI + FFmpeg) serves a Next.js static export (`frontend/out/`) on `localhost:8000`
- No separate Node/TypeScript server — FastAPI mounts `frontend/out/` as static files

## Key Files
- `main.py` — FastAPI app entry point, monitor endpoints, WebSocket `/ws/dashboard`, static file mount
- `services/auto_editor.py` — All FFmpeg calls use `asyncio.create_subprocess_exec` (async-correct)
- `services/llm_engine.py` — Multi-provider LLM with circuit breaker + template fallback
- `services/smart_crop.py` — Aspect-safe zoompan with smoothstep ease-in-out
- `services/compositor.py` — Multi-layer overlay + single-pass LUT chain
- `services/clip_analyzer.py` — VAD + OCR + loud peaks context in LLM prompt
- `services/ai_analysis.py` — `_extract_audio()`/`_extract_frames()` wrapped with `asyncio.to_thread`
- `services/edit_spec.py` — Edit spec generation with `_utcnow()` helper
- `services/audio_analyzer.py` — `get_voice_activity()` via FFmpeg silencedetect
- `services/face_tracker.py` — MediaPipe primary, OpenCV Haar cascade fallback
- `shared/event_bus/` — In-memory / Redis async event bus
- `shared/event_schemas.py` — Event schemas with `_utcnow()` helper
- `shared/utils/async_subprocess.py` — `run_async()`, `check_async()`, `run_to_thread()` wrappers
- `api/routers/kick_clips.py` — Download endpoint, edit queue trigger, edit results
- `frontend/src/app/page.tsx` — Dashboard with service grid, bulk edit, pipeline timeline
- `frontend/src/app/studio/page.tsx` — AI Studio with Omni-Engine pipeline runner
- `tests/` — 49 test files, 992 tests, `pytest -x` to run

## Test Commands
- `python -m pytest tests/ -x` — full suite with fail-fast
- `python -m pytest tests/test_xxx.py -x -v` — single file

## Python Dependencies
- `requirements-base.txt` — FastAPI/API layer (light)
- `requirements-ml.txt` — torch/tensorflow/mediapipe (heavy)
- `requirements.txt` — pulls in both (monolith/CI)

## Environment Variables (LLM providers)
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`
- `GROQ_API_KEY`, `COHERE_API_KEY`, `CEREBRAS_API_KEY`, `TOGETHER_API_KEY`
- `COMPLETIONS_API_KEY`, `BAZAARLINK_API_KEY`, `OPENROUTER_API_KEY`
- `LLM_CB_THRESHOLD` (default: 3), `LLM_CB_RECOVERY` (default: 60.0)

## Known Patterns
- `datetime.utcnow()` → use `_utcnow()` helper or `datetime.now(timezone.utc)` (no extra parens)
- Blocking `subprocess.run` → wrap in `asyncio.to_thread()` or use `async_subprocess.run_async()`
- Template fallback in LLM engine always returns valid content (Rick Roll style)
