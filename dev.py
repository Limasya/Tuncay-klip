"""
Tek komutla geliştirme ortamı: FastAPI (API) + Next.js (frontend hot-reload).
Next.js rewrites /api/* → FastAPI :8000, böylece localhost:3000'de API çalışır.
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dev")

FASTAPI_PORT = 8000
NEXTJS_PORT = 3000
PROCS: list[subprocess.Popen] = []


def _start_fastapi():
    cmd = [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(FASTAPI_PORT), "--reload"]
    logger.info(f"Başlatılıyor [FastAPI]: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)
    PROCS.append(proc)
    return proc


def _start_nextjs():
    cmd = ["npx", "next", "dev", "--port", str(NEXTJS_PORT)]
    logger.info(f"Başlatılıyor [Next.js]: {' '.join(cmd)}")
    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
    proc = subprocess.Popen(
        cmd,
        cwd=frontend_dir,
        stdout=sys.stdout,
        stderr=sys.stderr,
        shell=True,
    )
    PROCS.append(proc)
    return proc


def main():
    fastapi = _start_fastapi()
    nextjs = _start_nextjs()

    logger.info("━" * 50)
    logger.info("  FastAPI : http://localhost:%d  (API + statik frontend)", FASTAPI_PORT)
    logger.info("  Next.js : http://localhost:%d  (hot-reload frontend, API proxied)", NEXTJS_PORT)
    logger.info("  Önerilen: http://localhost:%d", NEXTJS_PORT)
    logger.info("  Çıkmak için Ctrl+C")
    logger.info("━" * 50)

    try:
        fastapi.wait()
        nextjs.wait()
    except KeyboardInterrupt:
        logger.info("Kapatılıyor...")
    finally:
        for proc in PROCS:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    main()
