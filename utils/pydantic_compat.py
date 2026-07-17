"""Pydantic v2 compatibility layer.

Project now uses Pydantic v2, but we maintain compatibility for any v1-style code.
"""
from __future__ import annotations

import pydantic

_V2 = pydantic.VERSION.startswith("2.")


def _patch_v2() -> None:
    """Pydantic v2 için ``from pydantic import BaseSettings`` uyumluluğu.

    v2'de BaseSettings ``pydantic_settings`` paketine taşındı. Proje kodu hâlâ
    ``from pydantic import BaseSettings`` kullandığından, onu pydantic ad alanına
    geri enjekte ederiz (tek noktadan köprüleme).
    """
    if "BaseSettings" in pydantic.__dict__:
        return
    try:
        from pydantic_settings import BaseSettings
    except Exception:  # pragma: no cover - pydantic_settings kurulu değilse
        return
    pydantic.BaseSettings = BaseSettings


def _patch_v1() -> None:
    """Pydantic v1 için backward compatibility (artık kullanılmıyor)."""
    pass


if not _V2:
    _patch_v1()
else:
    _patch_v2()

