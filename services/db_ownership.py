"""
Database Ownership Layer — Hangi veri nerede yaşar?
─────────────────────────────────────────────────────
SQLite: Lightweight, development, local state
PostgreSQL: Production, relational data, full-text search

Kurallar:
  SQLite    → clips metadata, projects, preferences, archive state, graph state
  PostgreSQL→ clips (production), analytics, events, experiments, audit logs
  JSON files→ cache (Redis yoksa), ML model configs, feature flags
  Redis     → session cache, rate limit, real-time metrics, pub/sub
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("db.ownership")


class Datastore(str, Enum):
    """Veri depolama hedefleri."""
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    REDIS = "redis"
    JSON_FILE = "json_file"
    IN_MEMORY = "in_memory"


class DataDomain(str, Enum):
    """Veri domainleri — her biri belirli bir datastore'da yaşar."""
    # SQLite domainleri
    CLIPS = "clips"                    # clip metadata, thumbnails
    PROJECTS = "projects"              # timeline projects, tracks
    PREFERENCES = "preferences"        # user preferences
    ARCHIVE_STATE = "archive_state"    # kick VOD archive dedup
    GRAPH_STATE = "graph_state"        # intelligence graph persistence
    SUBTITLES = "subtitles"            # subtitle files metadata

    # PostgreSQL domainleri (production)
    ANALYTICS = "analytics"            # viewership, performance metrics
    EVENTS = "events"                  # event log, audit trail
    EXPERIMENTS = "experiments"        # A/B test assignments, results
    AUDIT_LOG = "audit_log"            # admin actions, config changes

    # Redis domainleri
    SESSION_CACHE = "session_cache"    # LLM response cache, API cache
    RATE_LIMIT = "rate_limit"          # rate limiter counters
    REALTIME_METRICS = "realtime_metrics"  # live metrics, counters
    PUBSUB = "pubsub"                  # event bus messages

    # JSON file domainleri
    ML_CONFIG = "ml_config"            # model configs, hyperparams
    FEATURE_FLAGS = "feature_flags"    # feature flag definitions
    GRAPH_JSON = "graph_json"          # intelligence graph backup

    # In-memory domainleri
    TRANSIENT = "transient"            # runtime state, counters


@dataclass
class DataOwnership:
    """Bir veri domaininin ownership bilgisi."""
    domain: DataDomain
    datastore: Datastore
    description: str
    ttl: int = 0  # 0 = persistent
    backup: bool = False
    replicate: bool = False
    query_pattern: str = ""  # "random", "sequential", "key-value", "time-series"


# ── Ownership Matrix ──

OWNERSHIP_MATRIX: dict[DataDomain, DataOwnership] = {
    # ══ SQLite ══
    DataDomain.CLIPS: DataOwnership(
        domain=DataDomain.CLIPS,
        datastore=Datastore.SQLITE,
        description="Clip metadata, file paths, favorites, export status",
        ttl=0,
        backup=True,
        query_pattern="random",
    ),
    DataDomain.PROJECTS: DataOwnership(
        domain=DataDomain.PROJECTS,
        datastore=Datastore.SQLITE,
        description="Timeline projects, tracks, clip arrangements",
        ttl=0,
        backup=True,
        query_pattern="random",
    ),
    DataDomain.PREFERENCES: DataOwnership(
        domain=DataDomain.PREFERENCES,
        datastore=Datastore.SQLITE,
        description="User preferences, platform settings",
        ttl=0,
        backup=True,
        query_pattern="key-value",
    ),
    DataDomain.ARCHIVE_STATE: DataOwnership(
        domain=DataDomain.ARCHIVE_STATE,
        datastore=Datastore.SQLITE,
        description="Kick VOD archive dedup state",
        ttl=0,
        backup=False,
        query_pattern="key-value",
    ),
    DataDomain.GRAPH_STATE: DataOwnership(
        domain=DataDomain.GRAPH_STATE,
        datastore=Datastore.SQLITE,
        description="Intelligence graph node/edge persistence",
        ttl=0,
        backup=True,
        query_pattern="graph",
    ),
    DataDomain.SUBTITLES: DataOwnership(
        domain=DataDomain.SUBTITLES,
        datastore=Datastore.SQLITE,
        description="Subtitle file paths and metadata",
        ttl=0,
        backup=False,
        query_pattern="sequential",
    ),

    # ══ PostgreSQL (production) ══
    DataDomain.ANALYTICS: DataOwnership(
        domain=DataDomain.ANALYTICS,
        datastore=Datastore.POSTGRESQL,
        description="Viewership metrics, clip performance, revenue data",
        ttl=0,
        backup=True,
        replicate=True,
        query_pattern="time-series",
    ),
    DataDomain.EVENTS: DataOwnership(
        domain=DataDomain.EVENTS,
        datastore=Datastore.POSTGRESQL,
        description="Event log (clip created, stream detected, etc.)",
        ttl=0,
        backup=True,
        replicate=True,
        query_pattern="time-series",
    ),
    DataDomain.EXPERIMENTS: DataOwnership(
        domain=DataDomain.EXPERIMENTS,
        datastore=Datastore.POSTGRESQL,
        description="A/B test assignments, variant results",
        ttl=0,
        backup=True,
        query_pattern="random",
    ),
    DataDomain.AUDIT_LOG: DataOwnership(
        domain=DataDomain.AUDIT_LOG,
        datastore=Datastore.POSTGRESQL,
        description="Admin actions, config changes, security events",
        ttl=0,
        backup=True,
        replicate=True,
        query_pattern="time-series",
    ),

    # ══ Redis ══
    DataDomain.SESSION_CACHE: DataOwnership(
        domain=DataDomain.SESSION_CACHE,
        datastore=Datastore.REDIS,
        description="LLM response cache, API response cache",
        ttl=300,
        backup=False,
        query_pattern="key-value",
    ),
    DataDomain.RATE_LIMIT: DataOwnership(
        domain=DataDomain.RATE_LIMIT,
        datastore=Datastore.REDIS,
        description="Rate limiter counters per IP/API key",
        ttl=60,
        backup=False,
        query_pattern="key-value",
    ),
    DataDomain.REALTIME_METRICS: DataOwnership(
        domain=DataDomain.REALTIME_METRICS,
        datastore=Datastore.REDIS,
        description="Live stream metrics, viewer counts, event rates",
        ttl=300,
        backup=False,
        query_pattern="time-series",
    ),
    DataDomain.PUBSUB: DataOwnership(
        domain=DataDomain.PUBSUB,
        datastore=Datastore.REDIS,
        description="Event bus pub/sub messages (when Redis backend)",
        ttl=60,
        backup=False,
        query_pattern="sequential",
    ),

    # ══ JSON Files ══
    DataDomain.ML_CONFIG: DataOwnership(
        domain=DataDomain.ML_CONFIG,
        datastore=Datastore.JSON_FILE,
        description="ML model configs, hyperparameters, thresholds",
        ttl=0,
        backup=True,
        query_pattern="key-value",
    ),
    DataDomain.FEATURE_FLAGS: DataOwnership(
        domain=DataDomain.FEATURE_FLAGS,
        datastore=Datastore.JSON_FILE,
        description="Feature flag definitions and rules",
        ttl=0,
        backup=False,
        query_pattern="key-value",
    ),
    DataDomain.GRAPH_JSON: DataOwnership(
        domain=DataDomain.GRAPH_JSON,
        datastore=Datastore.JSON_FILE,
        description="Intelligence graph backup/seed data",
        ttl=0,
        backup=False,
        query_pattern="graph",
    ),

    # ══ In-Memory ══
    DataDomain.TRANSIENT: DataOwnership(
        domain=DataDomain.TRANSIENT,
        datastore=Datastore.IN_MEMORY,
        description="Runtime counters, temporary state, request context",
        ttl=0,
        backup=False,
        query_pattern="random",
    ),
}


class OwnershipRegistry:
    """Database ownership yönetim katmanı."""

    def __init__(self):
        self._matrix = OWNERSHIP_MATRIX

    def get_store(self, domain: DataDomain) -> Datastore:
        """Bir domain'in hangi datastore'da yaşadığını söyle."""
        ownership = self._matrix.get(domain)
        if not ownership:
            return Datastore.IN_MEMORY
        return ownership.datastore

    def get_ownership(self, domain: DataDomain) -> DataOwnership:
        ownership = self._matrix.get(domain)
        if not ownership:
            return DataOwnership(domain=domain, datastore=Datastore.IN_MEMORY, description="unknown")
        return ownership

    def get_domains_for_store(self, store: Datastore) -> list[DataDomain]:
        """Belirli bir datastore'daki tüm domain'leri listele."""
        return [d for d, o in self._matrix.items() if o.datastore == store]

    def should_backup(self, domain: DataDomain) -> bool:
        ownership = self._matrix.get(domain)
        return ownership.backup if ownership else False

    def get_ttl(self, domain: DataDomain) -> int:
        ownership = self._matrix.get(domain)
        return ownership.ttl if ownership else 0

    def get_migration_plan(self) -> dict[str, Any]:
        """SQLite → PostgreSQL geçiş planı."""
        sqlite_domains = self.get_domains_for_store(Datastore.SQLITE)
        pg_domains = self.get_domains_for_store(Datastore.POSTGRESQL)

        return {
            "current_sqlite": [d.value for d in sqlite_domains],
            "target_postgresql": [d.value for d in pg_domains],
            "needs_migration": len(sqlite_domains) > 0,
            "migration_order": [
                DataDomain.ANALYTICS.value,
                DataDomain.EVENTS.value,
                DataDomain.EXPERIMENTS.value,
                DataDomain.AUDIT_LOG.value,
            ],
        }

    def describe(self) -> dict[str, str]:
        """Tüm ownership bilgilerini açıkla."""
        result = {}
        for domain, ownership in self._matrix.items():
            result[domain.value] = (
                f"{ownership.datastore.value}: {ownership.description}"
            )
        return result


# Singleton
ownership_registry = OwnershipRegistry()
