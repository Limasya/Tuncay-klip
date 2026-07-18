"""
Domain Registry — API endpoint'lerini domain bazlı gruplar.
──────────────────────────────────────────────────────────
Her domain kendi area_prefix'ine sahip, router'ları toplu olarak kaydeder.

Domainler:
  ai       → /api/ai/*       (LLM, recommendations, smart-editor, vector)
  media    → /api/media/*    (clips, edit, render, thumbnail, subtitle)
  kick     → /api/kick/*     (kick stream, archive, clips collector)
  analytics→ /api/analytics/*(analytics, preferences)
  pipeline → /api/pipeline/* (event-driven orchestrator)
  platform → /api/platform/* (projects, flags, experiments)
  admin    → /api/admin/*    (health, metrics, config, backup)
  search   → /api/search/*   (semantic search, graphql)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import FastAPI, APIRouter

logger = logging.getLogger("api.domains")


@dataclass
class Domain:
    name: str
    description: str
    routers: list[APIRouter] = field(default_factory=list)
    area_prefix: str = ""
    tags: list[dict[str, str]] = field(default_factory=list)

    def include_in(self, app: FastAPI) -> None:
        """Tüm router'ları uygulamaya ekle."""
        for router in self.routers:
            app.include_router(router, tags=[self.name.capitalize()])
            logger.debug("Domain '%s': registered router %s", self.name, getattr(router, "prefix", ""))

    @property
    def endpoint_count(self) -> int:
        count = 0
        for router in self.routers:
            if hasattr(router, "routes"):
                count += len(router.routes)
        return count


class DomainRegistry:
    """Tüm domain'leri yönetir."""

    def __init__(self):
        self._domains: dict[str, Domain] = {}

    def register(self, domain: Domain) -> None:
        self._domains[domain.name] = domain

    def get(self, name: str) -> Domain | None:
        return self._domains.get(name)

    def include_all(self, app: FastAPI) -> None:
        """Tüm domain'leri uygulamaya ekle."""
        for domain in self._domains.values():
            domain.include_in(app)
            logger.info(
                "Domain '%s' registered: %d routers, %d endpoints",
                domain.name, len(domain.routers), domain.endpoint_count,
            )

    def get_all_endpoints(self) -> dict[str, list[dict[str, Any]]]:
        """Tüm endpoint'leri domain bazlı listele."""
        result = {}
        for name, domain in self._domains.items():
            endpoints = []
            for router in domain.routers:
                if hasattr(router, "routes"):
                    for route in router.routes:
                        if hasattr(route, "methods"):
                            for method in route.methods:
                                endpoints.append({
                                    "method": method,
                                    "path": getattr(route, "path", ""),
                                    "name": getattr(route, "name", ""),
                                })
            result[name] = endpoints
        return result

    def get_stats(self) -> dict[str, Any]:
        """Domain istatistiklerini getir."""
        stats = {}
        total_endpoints = 0
        total_routers = 0
        for name, domain in self._domains.items():
            ec = domain.endpoint_count
            rc = len(domain.routers)
            stats[name] = {"routers": rc, "endpoints": ec}
            total_endpoints += ec
            total_routers += rc
        stats["_total"] = {"routers": total_routers, "endpoints": total_endpoints}
        return stats


# ── Singleton ──
domain_registry = DomainRegistry()


# ── Domain Tanımları ──

def build_ai_domain() -> Domain:
    """AI/LLM domain — LLM engine, recommendations, smart editor."""
    from api.routers import llm_status, recommendations, smart_editor
    return Domain(
        name="ai",
        description="LLM engine, recommendations, smart editor, vector search",
        routers=[llm_status.router, recommendations.router, smart_editor.router],
        tags=[
            {"name": "LLM", "description": "LLM provider management, routing, testing"},
            {"name": "Recommendations", "description": "ML-powered clip recommendations"},
            {"name": "Smart Editor", "description": "AI-assisted editing and optimization"},
        ],
    )


def build_media_domain() -> Domain:
    """Media domain — clips, edit, render."""
    from api.routers import clips, edit
    return Domain(
        name="media",
        description="Clips CRUD, edit operations, render pipeline",
        routers=[clips.router, edit.router],
        tags=[
            {"name": "Clips", "description": "Clip management and CRUD"},
            {"name": "Edit", "description": "Video editing, subtitles, effects, rendering"},
        ],
    )


def build_kick_domain() -> Domain:
    """Kick domain — kick stream, archive, clips collector."""
    from api.routers import system, social
    return Domain(
        name="kick",
        description="Kick stream monitoring, VOD archive, clips collection",
        routers=[system.router, social.router],
        tags=[
            {"name": "Kick", "description": "Kick.com stream monitoring and management"},
        ],
    )


def build_analytics_domain() -> Domain:
    """Analytics domain — analytics, preferences."""
    from api.routers import analytics, preferences
    return Domain(
        name="analytics",
        description="Analytics, metrics, user preferences",
        routers=[analytics.router, preferences.router],
        tags=[
            {"name": "Analytics", "description": "Viewership and performance analytics"},
            {"name": "Preferences", "description": "User preferences management"},
        ],
    )


def build_pipeline_domain() -> Domain:
    """Pipeline domain — event-driven orchestrator."""
    from api.routers import pipeline
    return Domain(
        name="pipeline",
        description="Event-driven stream processing pipeline",
        routers=[pipeline.router],
        tags=[
            {"name": "Pipeline", "description": "Stream processing and event management"},
        ],
    )


def build_platform_domain() -> Domain:
    """Platform domain — projects, feature flags, experiments."""
    from api.routers import projects
    routers = [projects.router]

    try:
        from api.routers import platform
        routers.append(platform.router)
    except Exception as e:
        logger.debug("platform router yüklenemedi: %s", e)

    return Domain(
        name="platform",
        description="Projects, feature flags, A/B experiments",
        routers=routers,
        tags=[
            {"name": "Projects", "description": "Project management"},
            {"name": "Platform", "description": "Feature flags and experiments"},
        ],
    )


def build_admin_domain() -> Domain:
    """Admin domain — health, metrics, config."""
    routers = []
    try:
        from api.routers import admin
        routers.append(admin.router)
    except Exception as e:
        logger.debug("admin router yüklenemedi: %s", e)

    return Domain(
        name="admin",
        description="Admin API — health, metrics, service management",
        routers=routers,
        tags=[
            {"name": "Admin", "description": "Admin API for system management"},
        ],
    )


def build_search_domain() -> Domain:
    """Search domain — semantic search, GraphQL."""
    from api.routers import search, graphql
    return Domain(
        name="search",
        description="Semantic search and GraphQL",
        routers=[search.router, graphql.router],
        tags=[
            {"name": "Search", "description": "Semantic clip search"},
            {"name": "GraphQL", "description": "GraphQL API"},
        ],
    )


def build_knowledge_domain() -> Domain:
    """Knowledge Base domain — tüm yayınların bilgi bankası."""
    from api.routers import knowledge_base
    return Domain(
        name="knowledge",
        description="Knowledge Base — stream facts, participants, topics, game events",
        routers=[knowledge_base.router],
        tags=[
            {"name": "Knowledge Base", "description": "Structured knowledge about all streams"},
        ],
    )


def build_advanced_domain() -> Domain:
    """Advanced features domain — FAZ-2/3/4 features."""
    from api.routers import advanced
    return Domain(
        name="advanced",
        description="Advanced features — signal fusion, clip optimization, publisher, A/B test, subtitles, quality, costs, feedback",
        routers=[advanced.router],
        tags=[
            {"name": "Advanced", "description": "FAZ-2/3/4 advanced features"},
        ],
    )


def register_all_domains(registry: DomainRegistry | None = None) -> DomainRegistry:
    """Tüm domain'leri kaydet."""
    reg = registry or domain_registry

    builders = [
        build_ai_domain,
        build_media_domain,
        build_kick_domain,
        build_analytics_domain,
        build_pipeline_domain,
        build_platform_domain,
        build_admin_domain,
        build_search_domain,
        build_knowledge_domain,
        build_advanced_domain,
    ]

    for builder in builders:
        try:
            domain = builder()
            reg.register(domain)
        except Exception as e:
            logger.warning("Domain '%s' registration failed: %s", builder.__name__, e)

    return reg
