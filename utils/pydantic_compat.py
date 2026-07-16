"""Pydantic v1/v2 compatibility layer.

We standardise the project on Pydantic v1 (1.10.x) because FastAPI 0.100.x
ships against it and several downstream modules depend on v1 ``Config`` semantics.
Several microservice modules were originally written for Pydantic v2 and use
``model_dump()``/``model_validate()``.  Rather than sprinkle conditional
attribute access across 33 call sites, we monkeypatch the v1 BaseModel to
expose the v2-style methods.
"""
from __future__ import annotations

import json
import pydantic

_V2 = pydantic.VERSION.startswith("2.")


def _patch_v1() -> None:
    from pydantic import BaseModel as _V1BaseModel

    if hasattr(_V1BaseModel, "_compat_patched"):
        return

    def _model_dump(self, **kwargs):
        mode = kwargs.pop("mode", "python")
        exclude_unset = kwargs.pop("exclude_unset", False)
        exclude_defaults = kwargs.pop("exclude_defaults", False)
        exclude_none = kwargs.pop("exclude_none", False)
        if mode == "json":
            return json.loads(self.json(
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
            ))
        return self.dict(
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            **kwargs,
        )

    @classmethod
    def _model_validate(cls, obj):
        if isinstance(obj, dict):
            return cls.parse_obj(obj)
        return cls.from_orm(obj)

    _V1BaseModel.model_dump = _model_dump
    _V1BaseModel.model_validate = _model_validate
    _V1BaseModel._compat_patched = True


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


if not _V2:
    _patch_v1()
else:
    _patch_v2()

