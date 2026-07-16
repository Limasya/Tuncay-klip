"""
Feature Flag istemcisi (IP_PART6 Bölüm 37.1-37.3).

Deploy != Release: kod production'da olsa bile flag kapalıyken kullanıcıya
görünmez. Desteklenen yetenekler:
  - Aç/kapa (kill switch — ops toggle, 37.2)
  - Kademeli açılım (percentage rollout) — deterministik hash ile stabil (37.3)
  - Hedefleme (plan / region / açık targetingKey listesi)

Backend olarak in-memory / dict / JSON dosyası kullanılır (Unleash yerine hafif,
harici bağımlılıksız bir implementasyon). Değerlendirme mantığı OpenFeature
context modeliyle uyumludur: context = {"targetingKey": ..., "plan": ..., ...}.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class FlagType(str, Enum):
    """IP_PART6 37.2 — flag türleri."""

    RELEASE = "release"
    EXPERIMENT = "experiment"
    OPS = "ops"
    PERMISSION = "permission"


def _bucket(flag_key: str, unit_id: str) -> int:
    """Stabil, deterministik 0..99 kovası (percentage rollout için)."""
    digest = hashlib.sha256(f"{flag_key}:{unit_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


@dataclass
class FlagRule:
    """Tek bir feature flag'in değerlendirme kuralı."""

    key: str
    enabled: bool = False
    flag_type: FlagType = FlagType.RELEASE
    rollout_percentage: int = 100            # enabled iken % kaç kullanıcı
    enabled_plans: Optional[frozenset[str]] = None    # None => tüm planlar
    enabled_regions: Optional[frozenset[str]] = None  # None => tüm bölgeler
    enabled_targets: frozenset[str] = field(default_factory=frozenset)  # açık allowlist
    disabled_targets: frozenset[str] = field(default_factory=frozenset)  # açık blocklist

    def evaluate(self, context: dict[str, Any]) -> bool:
        """Verilen context için flag açık mı?"""
        target = str(context.get("targetingKey", ""))

        # açık blocklist her şeyi ezer
        if target and target in self.disabled_targets:
            return False
        # açık allowlist flag kapalı olsa bile açar (beta erişim)
        if target and target in self.enabled_targets:
            return True

        if not self.enabled:
            return False

        # plan hedefleme
        if self.enabled_plans is not None:
            if str(context.get("plan", "")) not in self.enabled_plans:
                return False

        # bölge hedefleme
        if self.enabled_regions is not None:
            if str(context.get("region", "")) not in self.enabled_regions:
                return False

        # kademeli açılım
        if self.rollout_percentage >= 100:
            return True
        if self.rollout_percentage <= 0:
            return False
        if not target:
            # targetingKey yoksa deterministik olamaz → yüzdeye göre açma
            return False
        return _bucket(self.key, target) < self.rollout_percentage

    @classmethod
    def from_dict(cls, key: str, data: dict[str, Any]) -> "FlagRule":
        def _fs(name: str) -> Optional[frozenset[str]]:
            val = data.get(name)
            return frozenset(str(x) for x in val) if val is not None else None

        return cls(
            key=key,
            enabled=bool(data.get("enabled", False)),
            flag_type=FlagType(data.get("type", "release")),
            rollout_percentage=int(data.get("rollout_percentage", 100)),
            enabled_plans=_fs("enabled_plans"),
            enabled_regions=_fs("enabled_regions"),
            enabled_targets=frozenset(str(x) for x in data.get("enabled_targets", [])),
            disabled_targets=frozenset(str(x) for x in data.get("disabled_targets", [])),
        )


class FeatureFlagClient:
    """
    Feature flag değerlendirme istemcisi.

    Kaynak: bir dict ya da JSON dosyası. reload() ile yeniden yüklenebilir.
    """

    def __init__(self, flags: Optional[dict[str, FlagRule]] = None) -> None:
        self._flags: dict[str, FlagRule] = flags or {}

    # -- yükleme --------------------------------------------------------------
    @classmethod
    def from_dict(cls, config: dict[str, dict]) -> "FeatureFlagClient":
        flags = {k: FlagRule.from_dict(k, v) for k, v in config.items()}
        return cls(flags)

    @classmethod
    def from_file(cls, path: str | Path) -> "FeatureFlagClient":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    def reload(self, config: dict[str, dict]) -> None:
        self._flags = {k: FlagRule.from_dict(k, v) for k, v in config.items()}

    # -- değerlendirme --------------------------------------------------------
    def get_boolean_value(
        self,
        key: str,
        default: bool = False,
        context: Optional[dict[str, Any]] = None,
    ) -> bool:
        """
        Flag değerini döndürür (OpenFeature uyumlu imza).

        Bilinmeyen flag => default (fail-safe).
        """
        rule = self._flags.get(key)
        if rule is None:
            return default
        return rule.evaluate(context or {})

    def set_flag(self, rule: FlagRule) -> None:
        self._flags[rule.key] = rule

    def all_flags(self) -> dict[str, FlagRule]:
        return dict(self._flags)


# Uygulama genelinde paylaşılan varsayılan istemci.
default_client = FeatureFlagClient()


def is_enabled(key: str, context: Optional[dict[str, Any]] = None, default: bool = False) -> bool:
    """default_client üzerinden kısayol."""
    return default_client.get_boolean_value(key, default, context)
