"""
Integration test for dev.py launcher and Next.js API proxy rewrites.

Verifies:
  - dev.py starts FastAPI on port 8000 and Next.js on port 3000
  - GET /api/system/status returns valid JSON via both ports
  - Next.js proxy rewrites work (port 3000 → port 8000)

Requires: next build already done (frontend/out/ exists)
Mark: slow (network + subprocess)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
DEV_PY = PROJECT_ROOT / "dev.py"


def _kill_port(port: int) -> None:
    """Best-effort kill of any process listening on localhost:<port>."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | "
                 f"ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"],
                capture_output=True, timeout=5,
            )
        else:
            subprocess.run(f"fuser -k {port}/tcp || true", shell=True, capture_output=True, timeout=5)
    except Exception:
        pass


def _wait_for_port(port: int, timeout: float = 15.0) -> bool:
    """Poll until localhost:<port> responds with any HTTP status."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://localhost:{port}/", timeout=2)
            return True
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            pass
        time.sleep(0.5)
    return False


def _json_get(port: int, path: str) -> dict | None:
    """GET from localhost:<port><path> and return parsed JSON or None."""
    try:
        with urllib.request.urlopen(f"http://localhost:{port}{path}", timeout=5) as f:
            return json.loads(f.read().decode())
    except Exception:
        return None


@pytest.mark.slow
class TestDevLauncherAndProxy:
    """Start dev.py, verify both servers respond, then stop."""

    @pytest.fixture(scope="class")
    def dev_process(self):
        """Start dev.py, wait for both servers, yield, then stop."""
        if not DEV_PY.exists():
            pytest.skip("dev.py not found")
        if not (PROJECT_ROOT / "frontend" / "out" / "index.html").exists():
            pytest.skip("frontend/out/ not built — run 'npm run build' in frontend/ first")

        # Clear any lingering processes on the test ports
        _kill_port(8000)
        _kill_port(3000)
        time.sleep(1)

        proc = subprocess.Popen(
            [sys.executable, str(DEV_PY)],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        ok8000 = _wait_for_port(8000, timeout=20)
        ok3000 = _wait_for_port(3000, timeout=10)

        if not ok8000 or not ok3000:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            _kill_port(8000)
            _kill_port(3000)
            ports = f"8000={'OK' if ok8000 else 'TIMEOUT'} 3000={'OK' if ok3000 else 'TIMEOUT'}"
            pytest.fail(f"dev.py servers did not start: {ports}")

        yield proc

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        # Best-effort cleanup of any lingering port listeners
        _kill_port(8000)
        _kill_port(3000)

    def test_fastapi_status(self, dev_process):
        """FastAPI /api/system/status returns valid JSON."""
        data = _json_get(8000, "/api/system/status")
        assert data is not None, "FastAPI did not respond"
        assert isinstance(data, dict)
        assert "is_monitoring" in data or "status" in data

    def test_nextjs_serves_frontend(self, dev_process):
        """Next.js dev server returns HTML (not error)."""
        try:
            with urllib.request.urlopen("http://localhost:3000/", timeout=5) as f:
                body = f.read().decode()
            assert "<html" in body.lower() or "<!doctype" in body.lower()
        except Exception as e:
            pytest.fail(f"Next.js frontend not reachable: {e}")

    def test_nextjs_proxy_fastapi(self, dev_process):
        """Next.js proxy forwards /api/system/status to FastAPI."""
        data_via_next = _json_get(3000, "/api/system/status")
        data_via_fast = _json_get(8000, "/api/system/status")

        assert data_via_next is not None, "Next.js proxy did not respond"
        assert isinstance(data_via_next, dict)

        # Both should return the same kind of data (real proxy, not stub)
        if data_via_fast:
            keys_next = set(data_via_next.keys())
            keys_fast = set(data_via_fast.keys())
            common = keys_next & keys_fast
            assert len(common) >= 1, (
                f"Proxy response differs from direct. "
                f"Via Next.js keys: {sorted(keys_next)} vs Via FastAPI keys: {sorted(keys_fast)}"
            )

    def test_nextjs_returns_json_not_html_for_api(self, dev_process):
        """Proxy returns JSON (not HTML) for API calls."""
        try:
            with urllib.request.urlopen("http://localhost:3000/api/system/status", timeout=5) as f:
                content_type = f.headers.get("Content-Type", "")
                body = f.read().decode()
        except Exception as e:
            pytest.fail(f"Could not fetch: {e}")

        assert "html" not in content_type.lower(), f"Got HTML instead of JSON: {content_type}"
        try:
            parsed = json.loads(body)
            assert isinstance(parsed, dict)
        except json.JSONDecodeError:
            pytest.fail(f"Response is not valid JSON: {body[:120]}")