"""
Cost Tracker — Maliyet ve Kullanım İzleme
─────────────────────────────────────────
FAZ-4.2: LLM API çağrıları, FFmpeg işlemleri, depolama maliyetleri.

Features:
  - LLM API cost tracking (token bazlı)
  - FFmpeg processing cost (işlem süresi)
  - Storage cost estimation
  - Platform bazında maliyet dağılımı
  - Günlük/haftalık/maliyet raporları
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.llm_model_defaults import get_gemini_model_default


# ── Pricing per 1M tokens (USD) ──
LLM_PRICING: Dict[str, Dict[str, float]] = {
    "openai": {"input": 0.15, "output": 0.60, "model": "gpt-4o-mini"},
    "anthropic": {"input": 0.25, "output": 1.25, "model": "claude-3-haiku"},
    "gemini": {"input": 0.075, "output": 0.30, "model": get_gemini_model_default()},
    "groq": {"input": 0.05, "output": 0.10, "model": "llama-3.1-70b"},
    "ollama": {"input": 0.0, "output": 0.0, "model": "local"},
    "deepseek": {"input": 0.14, "output": 0.28, "model": "deepseek-chat"},
    "mistral": {"input": 0.25, "output": 0.75, "model": "mistral-small"},
    "cohere": {"input": 0.15, "output": 0.60, "model": "command-r"},
}


class CostRecord(BaseModel):
    """Tek bir maliyet kaydı."""
    record_id: str = ""
    category: str = ""  # "llm", "ffmpeg", "storage", "upload"
    subcategory: str = ""  # provider name, operation type
    clip_id: str = ""
    amount_usd: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0
    processing_seconds: float = 0.0
    file_size_bytes: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CostSummary(BaseModel):
    """Dönem maliyet özeti."""
    period: str = ""
    total_usd: float = 0.0
    by_category: Dict[str, float] = Field(default_factory=dict)
    by_provider: Dict[str, float] = Field(default_factory=dict)
    by_clip: Dict[str, float] = Field(default_factory=dict)
    clip_count: int = 0
    avg_cost_per_clip: float = 0.0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    total_processing_seconds: float = 0.0


class CostTracker:
    """
    Maliyet ve kullanım izleme sistemi.
    """

    def __init__(self, state_path: str | Path | None = None):
        self._records: List[CostRecord] = []
        self._state_path = Path(state_path or "data/cost_tracker_state.json")
        self._record_counter: int = 0

    # ── Recording ──

    def record_llm_call(
        self,
        provider: str,
        tokens_input: int,
        tokens_output: int,
        clip_id: str = "",
        model: str = "",
    ) -> CostRecord:
        """LLM API çağrısı maliyetini kaydet."""
        pricing = LLM_PRICING.get(provider, LLM_PRICING.get("openai"))
        input_cost = (tokens_input / 1_000_000) * pricing["input"]
        output_cost = (tokens_output / 1_000_000) * pricing["output"]
        total_cost = input_cost + output_cost

        self._record_counter += 1
        record = CostRecord(
            record_id=f"cost_{self._record_counter:06d}",
            category="llm",
            subcategory=provider,
            clip_id=clip_id,
            amount_usd=round(total_cost, 6),
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            metadata={
                "model": model or pricing.get("model", ""),
                "input_cost": round(input_cost, 6),
                "output_cost": round(output_cost, 6),
            },
        )
        self._records.append(record)
        return record

    def record_ffmpeg_process(
        self,
        operation: str,
        duration_seconds: float,
        clip_id: str = "",
    ) -> CostRecord:
        """FFmpeg işleme maliyetini kaydet."""
        # FFmpeg maliyeti: CPU/saniye bazlı tahmini
        # Ortalama sunucu: $0.05/saat = $0.0000139/saniye
        cpu_cost_per_sec = 0.0000139
        cost = duration_seconds * cpu_cost_per_sec

        self._record_counter += 1
        record = CostRecord(
            record_id=f"cost_{self._record_counter:06d}",
            category="ffmpeg",
            subcategory=operation,
            clip_id=clip_id,
            amount_usd=round(cost, 6),
            processing_seconds=duration_seconds,
            metadata={"operation": operation},
        )
        self._records.append(record)
        return record

    def record_storage(
        self,
        file_size_bytes: int,
        file_type: str = "video",
        clip_id: str = "",
    ) -> CostRecord:
        """Depolama maliyetini kaydet."""
        # S3: $0.023/GB/ay
        gb = file_size_bytes / (1024 ** 3)
        cost = gb * 0.023 / 30  # günlük

        self._record_counter += 1
        record = CostRecord(
            record_id=f"cost_{self._record_counter:06d}",
            category="storage",
            subcategory=file_type,
            clip_id=clip_id,
            amount_usd=round(cost, 6),
            file_size_bytes=file_size_bytes,
        )
        self._records.append(record)
        return record

    def record_upload(
        self,
        platform: str,
        file_size_bytes: int,
        clip_id: str = "",
    ) -> CostRecord:
        """Yükleme maliyetini kaydet."""
        # Upload maliyeti genelde ücretsiz, bandwidth maliyeti çok düşük
        cost = 0.0001  # $0.1/TB varsayımıyla

        self._record_counter += 1
        record = CostRecord(
            record_id=f"cost_{self._record_counter:06d}",
            category="upload",
            subcategory=platform,
            clip_id=clip_id,
            amount_usd=cost,
            file_size_bytes=file_size_bytes,
        )
        self._records.append(record)
        return record

    # ── Reporting ──

    def get_daily_costs(self, days: int = 30) -> List[Dict[str, Any]]:
        """Günlük maliyet raporu."""
        now = datetime.now(timezone.utc)
        daily = defaultdict(lambda: {"total": 0.0, "categories": defaultdict(float)})

        for record in self._records:
            try:
                rec_time = datetime.fromisoformat(record.timestamp.replace("Z", "+00:00"))
                if (now - rec_time).days > days:
                    continue
                day_key = rec_time.strftime("%Y-%m-%d")
                daily[day_key]["total"] += record.amount_usd
                daily[day_key]["categories"][record.category] += record.amount_usd
            except Exception as e:
                logger.debug("Cost record parse failed: %s", e)
                continue

        return [
            {
                "date": date,
                "total_usd": round(data["total"], 4),
                "categories": {k: round(v, 4) for k, v in data["categories"].items()},
            }
            for date, data in sorted(daily.items())
        ]

    def get_summary(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> CostSummary:
        """Maliyet özeti."""
        filtered = self._records

        if start_time:
            filtered = [
                r for r in filtered
                if r.timestamp >= start_time
            ]
        if end_time:
            filtered = [
                r for r in filtered
                if r.timestamp <= end_time
            ]

        total = sum(r.amount_usd for r in filtered)
        by_category = defaultdict(float)
        by_provider = defaultdict(float)
        by_clip = defaultdict(float)
        total_input_tokens = 0
        total_output_tokens = 0
        total_processing = 0.0

        for r in filtered:
            by_category[r.category] += r.amount_usd
            by_provider[r.subcategory] += r.amount_usd
            if r.clip_id:
                by_clip[r.clip_id] += r.amount_usd
            total_input_tokens += r.tokens_input
            total_output_tokens += r.tokens_output
            total_processing += r.processing_seconds

        clip_ids = set(r.clip_id for r in filtered if r.clip_id)

        return CostSummary(
            total_usd=round(total, 4),
            by_category={k: round(v, 4) for k, v in by_category.items()},
            by_provider={k: round(v, 4) for k, v in by_provider.items()},
            by_clip={k: round(v, 4) for k, v in sorted(by_clip.items(), key=lambda x: x[1], reverse=True)[:20]},
            clip_count=len(clip_ids),
            avg_cost_per_clip=round(total / max(1, len(clip_ids)), 4),
            total_tokens_input=total_input_tokens,
            total_tokens_output=total_output_tokens,
            total_processing_seconds=round(total_processing, 1),
        )

    def get_current_month_cost(self) -> float:
        """Bu ayki toplam maliyet."""
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.get_summary(
            start_time=month_start.isoformat()
        ).total_usd

    def estimate_clip_cost(self, clip_id: str) -> Dict[str, float]:
        """Tek bir klibin tahmini maliyeti."""
        clip_records = [r for r in self._records if r.clip_id == clip_id]
        costs = defaultdict(float)
        for r in clip_records:
            costs[r.category] += r.amount_usd

        return {k: round(v, 6) for k, v in costs.items()}

    # ── Query ──

    def get_records(
        self,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        records = self._records
        if category:
            records = [r for r in records if r.category == category]
        return [r.model_dump() for r in records[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_records": len(self._records),
            "total_cost_usd": round(sum(r.amount_usd for r in self._records), 4),
            "categories": list(set(r.category for r in self._records)),
            "providers": list(set(r.subcategory for r in self._records if r.category == "llm")),
            "total_tokens": sum(r.tokens_input + r.tokens_output for r in self._records),
            "total_processing_hours": round(
                sum(r.processing_seconds for r in self._records) / 3600, 2
            ),
        }

    # ── Persistence ──

    async def save(self) -> None:
        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "records": [r.model_dump() for r in self._records[-2000:]],
            "counter": self._record_counter,
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._state_path.with_suffix(".tmp")
        await asyncio.to_thread(
            temp.write_text,
            json.dumps(state, ensure_ascii=False, indent=2, default=str),
            "utf-8",
        )
        await asyncio.to_thread(temp.replace, self._state_path)

    async def load(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = await asyncio.to_thread(self._state_path.read_text, encoding="utf-8")
            state = json.loads(data)
            self._records = [CostRecord(**r) for r in state.get("records", [])]
            self._record_counter = state.get("counter", len(self._records))
        except Exception as e:
            logger.warning("Cost tracker state load failed: %s", e)


# Singleton
cost_tracker = CostTracker()
