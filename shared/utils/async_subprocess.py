"""Async subprocess helper — blocking subprocess.run yerine asyncio wrapper'lari.

Ornek:
    from shared.utils.async_subprocess import run_async, check_async
    rc, stdout, stderr = await run_async(["ffprobe", "-version"], timeout=10)
    if await check_async(["yt-dlp", "--version"]):
        ...
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def run_async(
    cmd: list[str],
    timeout: float = 120,
    capture_output: bool = True,
) -> tuple[int, str, str]:
    """subprocess.run'un async versiyonu.

    Returns:
        (returncode, stdout_str, stderr_str)
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE if capture_output else None,
        stderr=asyncio.subprocess.PIPE if capture_output else None,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("Timeout (%.1fs): %s", timeout, cmd[0])
        return -1, "", "timeout"

    out_str = stdout.decode(errors="replace") if stdout else ""
    err_str = stderr.decode(errors="replace") if stderr else ""
    return proc.returncode or 0, out_str, err_str


async def check_async(cmd: list[str], timeout: float = 30) -> bool:
    """subprocess.check_output'un async versiyonu — bool doner."""
    rc, _, _ = await run_async(cmd, timeout=timeout)
    return rc == 0


async def run_to_thread(
    fn, *args, timeout: Optional[float] = None, **kwargs
):
    """asyncio.to_thread wrapper'i — blocking sync fonksiyonu event loop'u bloke etmeden calistirir.

    Ornek:
        result = await run_to_thread(subprocess.run, cmd, capture_output=True, timeout=30)
    """
    return await asyncio.wait_for(
        asyncio.to_thread(fn, *args, **kwargs),
        timeout=timeout,
    )
