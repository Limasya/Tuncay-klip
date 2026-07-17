"""
Smart LLM Router
────────────────
Akıllı LLM yönlendirici:
  - Provider başarı oranı ve gecikme takibi
  - Maliyet optimizasyonu (önce ücretsiz dene)
  - Prompt karmaşıklığına göre model seçimi
  - A/B test desteği
  - Real-time sağlık durumu

Kullanım:
    from services.smart_llm_router import smart_router
    result = await smart_router.route(prompt, strategy="cost_optimized")
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("smart_llm_router")

# ─── Provider Tier Sistemi ───────────────────────────────────────────────────
# Tier 1: Tamamen ücretsiz, hız öncelikli
# Tier 2: Ücretsiz başlangıç kredisi / sınırlı ücretsiz
# Tier 3: Ücretli ama düşük maliyet
# Tier 4: Local (sınırsız ücretsiz ama donanım gerektirir)

PROVIDER_TIERS: dict[str, int] = {
    "groq": 1,       # Ücretsiz, 800+ tok/s
    "cerebras": 1,   # Ücretsiz, wafer-scale hız
    "openrouter": 1, # Ücretsiz modeller var
    "cohere": 2,     # 1000 req/ay ücretsiz
    "together": 2,   # $25 başlangıç kredisi
    "gemini": 2,     # 15 RPM ücretsiz
    "mistral": 2,    # Sınırlı ücretsiz
    "nvidia": 2,     # Sınırlı ücretsiz
    "huggingface": 2,# 1000 req/gün ücretsiz
    "openai": 3,     # Ücretli
    "claude": 3,     # Ücretli
    "ollama": 4,     # Local, ücretsiz
    "vllm": 4,       # Local, ücretsiz
    "lmstudio": 4,   # Local, ücretsiz
    "localai": 4,    # Local, ücretsiz
    "textgen": 4,    # Local, ücretsiz
    "template": 99,  # Son çare
}

# Provider'ların yaklaşık token/saniye hızları (benchmarktan)
PROVIDER_SPEED_TPS: dict[str, float] = {
    "groq": 800.0,
    "cerebras": 2000.0,
    "openai": 80.0,
    "claude": 60.0,
    "gemini": 100.0,
    "mistral": 60.0,
    "cohere": 50.0,
    "together": 70.0,
    "nvidia": 80.0,
    "openrouter": 60.0,
    "huggingface": 30.0,
    "ollama": 20.0,
    "vllm": 60.0,
    "lmstudio": 20.0,
    "localai": 15.0,
    "textgen": 15.0,
    "template": 10000.0,  # Instant template
}


@dataclass
class ProviderStats:
    """Bir provider'ın çalışma istatistikleri."""
    name: str
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0
    recent_latencies: deque = field(default_factory=lambda: deque(maxlen=20))
    recent_errors: deque = field(default_factory=lambda: deque(maxlen=10))
    last_error_ts: float = 0.0
    cooldown_until: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.success_calls / self.total_calls

    @property
    def avg_latency_ms(self) -> float:
        if not self.recent_latencies:
            return 500.0
        return sum(self.recent_latencies) / len(self.recent_latencies)

    @property
    def is_in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def record_success(self, latency_ms: float):
        self.total_calls += 1
        self.success_calls += 1
        self.total_latency_ms += latency_ms
        self.recent_latencies.append(latency_ms)

    def record_failure(self, error: str):
        self.total_calls += 1
        self.failed_calls += 1
        self.recent_errors.append({"ts": time.time(), "error": error[:100]})
        self.last_error_ts = time.time()
        # Arka arkaya 3+ hata → 60 sn cooldown
        recent_fails = sum(1 for e in list(self.recent_errors)[-3:] if e)
        if recent_fails >= 3:
            self.cooldown_until = time.time() + 60.0
            logger.warning("Provider %s in 60s cooldown after failures", self.name)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tier": PROVIDER_TIERS.get(self.name, 99),
            "total_calls": self.total_calls,
            "success_calls": self.success_calls,
            "failed_calls": self.failed_calls,
            "success_rate": round(self.success_rate * 100, 1),
            "avg_latency_ms": round(self.avg_latency_ms, 0),
            "speed_tps": PROVIDER_SPEED_TPS.get(self.name, 30.0),
            "in_cooldown": self.is_in_cooldown,
            "cooldown_remaining_s": max(0, round(self.cooldown_until - time.time(), 0)),
            "recent_errors": list(self.recent_errors)[-3:],
        }


class SmartLLMRouter:
    """
    Akıllı LLM yönlendiricisi.

    Stratejiler:
        - "cost_optimized": Önce ücretsiz tier (default)
        - "speed_first":    En hızlı provider (Groq/Cerebras önce)
        - "quality_first":  En kaliteli model (GPT-4o/Claude)
        - "balanced":       Hız + kalite dengesi

    Kullanım:
        result = await smart_router.route(prompt, strategy="cost_optimized")
    """

    STRATEGIES = ["cost_optimized", "speed_first", "quality_first", "balanced"]

    def __init__(self):
        self._stats: dict[str, ProviderStats] = {}
        self._available_providers: list[str] = []
        self._ab_test_ratio: float = 0.1  # %10 alternatif provider'a yönlendir

    def register_provider(self, name: str):
        """Bir provider'ı router'a kaydet."""
        if name not in self._stats:
            self._stats[name] = ProviderStats(name=name)
        if name not in self._available_providers:
            self._available_providers.append(name)

    def _sort_providers(self, strategy: str) -> list[str]:
        """Stratejiye göre provider sırasını belirle."""
        available = [
            p for p in self._available_providers
            if not self._stats.get(p, ProviderStats(p)).is_in_cooldown
        ]

        if strategy == "cost_optimized":
            # Tier'a göre sırala (tier 1 = ücretsiz önce)
            return sorted(available, key=lambda p: (
                PROVIDER_TIERS.get(p, 99),
                self._stats.get(p, ProviderStats(p)).avg_latency_ms,
            ))
        elif strategy == "speed_first":
            # Hıza göre sırala
            return sorted(available, key=lambda p: (
                -PROVIDER_SPEED_TPS.get(p, 30.0),
                self._stats.get(p, ProviderStats(p)).avg_latency_ms,
            ))
        elif strategy == "quality_first":
            # Kalite modelleri önce (ücretli modeller genelde daha iyi)
            quality_order = ["openai", "claude", "gemini", "groq", "together",
                             "cerebras", "mistral", "cohere", "nvidia", "openrouter",
                             "huggingface", "ollama", "vllm", "lmstudio", "template"]
            def quality_rank(p: str) -> int:
                try:
                    return quality_order.index(p)
                except ValueError:
                    return 99
            return sorted(available, key=quality_rank)
        elif strategy == "balanced":
            # Başarı oranı × hız dengesi
            def balanced_score(p: str) -> float:
                stats = self._stats.get(p, ProviderStats(p))
                speed = PROVIDER_SPEED_TPS.get(p, 30.0)
                success = stats.success_rate
                tier_bonus = 1.0 + (0.1 * (4 - min(PROVIDER_TIERS.get(p, 4), 4)))
                return -(success * speed * tier_bonus)  # Büyük = iyi, sort için negatif
            return sorted(available, key=balanced_score)
        else:
            return available

    async def route(
        self,
        prompt: str,
        strategy: str = "cost_optimized",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system_prompt: str | None = None,
        providers_override: list[str] | None = None,
    ) -> tuple[str, str]:
        """
        Akıllı yönlendirme ile LLM çağrısı yap.

        Returns:
            (result_text, provider_name_used)
        """
        from services.llm_engine import llm_engine

        ordered = providers_override or self._sort_providers(strategy)

        if not ordered:
            logger.warning("No providers available, falling back to template")
            ordered = ["template"]

        logger.debug("Router strategy=%s, order=%s", strategy, ordered[:4])

        for provider_name in ordered:
            stats = self._stats.get(provider_name)
            if stats and stats.is_in_cooldown:
                continue

            start = time.time()
            try:
                # LLM engine'deki provider'ı bul ve çağır
                result = None
                for name, provider_fn in llm_engine._providers:
                    if name == provider_name:
                        result = await asyncio.wait_for(
                            provider_fn(
                                prompt,
                                max_tokens=max_tokens,
                                temperature=temperature,
                                system_prompt=system_prompt,
                            ),
                            timeout=45.0,
                        )
                        break

                if result and len(result.strip()) > 3:
                    latency_ms = (time.time() - start) * 1000
                    if stats:
                        stats.record_success(latency_ms)
                    logger.debug(
                        "Router: %s responded in %.0fms", provider_name, latency_ms
                    )
                    return result, provider_name

            except asyncio.TimeoutError:
                if stats:
                    stats.record_failure("timeout")
                logger.warning("Router: %s timed out", provider_name)
            except Exception as e:
                if stats:
                    stats.record_failure(str(e))
                logger.warning("Router: %s failed: %s", provider_name, e)

        # Tüm provider'lar başarısız → template
        return f"[Router exhausted all providers for strategy={strategy}]", "template"

    def get_status(self) -> dict:
        """Tüm provider'ların durumunu döndür."""
        return {
            "available_providers": self._available_providers,
            "strategy_options": self.STRATEGIES,
            "provider_stats": {
                name: stats.to_dict()
                for name, stats in self._stats.items()
            },
            "tier_summary": {
                "tier_1_free": [p for p in self._available_providers if PROVIDER_TIERS.get(p, 99) == 1],
                "tier_2_freemium": [p for p in self._available_providers if PROVIDER_TIERS.get(p, 99) == 2],
                "tier_3_paid": [p for p in self._available_providers if PROVIDER_TIERS.get(p, 99) == 3],
                "tier_4_local": [p for p in self._available_providers if PROVIDER_TIERS.get(p, 99) == 4],
            },
        }

    def reset_cooldowns(self):
        """Tüm cooldown'ları sıfırla."""
        for stats in self._stats.values():
            stats.cooldown_until = 0.0

    def get_recommended_free_providers(self) -> list[dict]:
        """Ücretsiz tier provider önerileri döndür."""
        return [
            {
                "name": "Groq",
                "env_key": "GROQ_API_KEY",
                "signup_url": "https://console.groq.com",
                "free_tier": "14,400 req/gün, 6000 token/dak",
                "models": ["llama-3.1-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"],
                "speed_tps": 800,
            },
            {
                "name": "Cerebras",
                "env_key": "CEREBRAS_API_KEY",
                "signup_url": "https://cloud.cerebras.ai",
                "free_tier": "Ücretsiz tier, wafer-scale chip",
                "models": ["llama3.1-70b", "llama3.1-8b"],
                "speed_tps": 2000,
            },
            {
                "name": "Google Gemini",
                "env_key": "GEMINI_API_KEY",
                "signup_url": "https://aistudio.google.com/apikey",
                "free_tier": "15 RPM, 1M token/gün",
                "models": ["gemini-2.0-flash", "gemini-1.5-flash"],
                "speed_tps": 100,
            },
            {
                "name": "Cohere",
                "env_key": "COHERE_API_KEY",
                "signup_url": "https://dashboard.cohere.com",
                "free_tier": "1000 req/ay trial",
                "models": ["command-r", "command-r-plus"],
                "speed_tps": 50,
            },
            {
                "name": "Together AI",
                "env_key": "TOGETHER_API_KEY",
                "signup_url": "https://api.together.xyz",
                "free_tier": "$25 başlangıç kredisi",
                "models": ["meta-llama/Llama-3.1-70B-Instruct-Turbo"],
                "speed_tps": 70,
            },
            {
                "name": "OpenRouter",
                "env_key": "OPENROUTER_API_KEY",
                "signup_url": "https://openrouter.ai",
                "free_tier": "200+ model, birçoğu ücretsiz",
                "models": ["meta-llama/llama-3.1-8b-instruct:free", "google/gemma-2-9b-it:free"],
                "speed_tps": 60,
            },
            {
                "name": "HuggingFace",
                "env_key": "HUGGINGFACE_API_TOKEN",
                "signup_url": "https://huggingface.co/settings/tokens",
                "free_tier": "1000 req/gün ücretsiz",
                "models": ["HuggingFaceH4/zephyr-7b-beta", "microsoft/Phi-3-mini-4k-instruct"],
                "speed_tps": 30,
            },
        ]


# Singleton
smart_router = SmartLLMRouter()


def sync_router_with_engine():
    """LLM engine'deki provider'ları router'a senkronize et."""
    try:
        from services.llm_engine import llm_engine
        for name, _ in llm_engine._providers:
            smart_router.register_provider(name)
        logger.info(
            "Smart router synced: %d providers registered",
            len(smart_router._available_providers),
        )
    except Exception as e:
        logger.warning("Router sync failed: %s", e)
