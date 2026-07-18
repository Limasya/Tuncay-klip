"""
JSON Dosya Tabanli Durum Saklama
────────────────────────────────
12+ serviste tekrar eden _load_state()/_save_state() pattern'ini birlestirir.
Atomic yazar: once .tmp dosyasina, sonra rename.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class JsonStateStore:
    """JSON dosyasinda kalici durum saklama.

    Ornegin:
        store = JsonStateStore("data/kick_archive_state.json")
        state = await store.load()
        state["vods"][vod_id] = {"status": "completed"}
        await store.save(state)
    """

    def __init__(self, path: str | Path, default_factory=None):
        self._path = Path(path)
        self._default_factory = default_factory or (lambda: {})

    @property
    def path(self) -> Path:
        return self._path

    def _read_sync(self) -> dict[str, Any]:
        if not self._path.exists():
            return self._default_factory()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else self._default_factory()
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("State dosyasi okunamadi (%s): %s", self._path, exc)
            return self._default_factory()

    def _write_sync(self, state: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    async def load(self) -> dict[str, Any]:
        """Asenkron olarak state dosyasini oku."""
        return await asyncio.to_thread(self._read_sync)

    async def save(self, state: dict[str, Any]) -> None:
        """Asenkron olarak state dosyasini atomik olarak yaz."""
        await asyncio.to_thread(self._write_sync, state)

    def exists(self) -> bool:
        return self._path.exists()
