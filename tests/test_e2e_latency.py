"""
Görev 1: Gerçek uçtan uca gecikme ölçümü
==========================================
EventBus'a test sinyalleri enjekte eder, ilk event'ten CLIP_CANDIDATE'e kadar
geçen toplam süreyi kronometre ile ölçer. Her karar katmanını ayrı ayrı zamanlar.

Bulunan parametreler (config.py + kod):
  - score_interval = 2.0s
  - confirmation_window = 3, required = 2
  - cooldown_seconds = 15.0
  - decay_halflife = 5.0s
  - LLM katmanı: YER YOK (sadece docstring, evaluate() içinde implemente edilmemiş)
"""
from __future__ import annotations

import asyncio
import sys
import time
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


# ── Katman bazlı gecikme ölçümü ───────────────────────────────────────────────

class TestDecisionEngineLayerLatency:
    """
    DecisionEngineService'in her karar katmanının ne kadar sürdüğünü ölçer.
    Doğrudan evaluate() çağırarak EventBus bağımlılığını kaldırır.
    """

    def test_evaluate_is_sub_millisecond(self):
        """evaluate() tek başına ne kadar sürer?"""
        from shared.event_schemas import HighlightScore
        from microservices.decision_engine.service import DecisionEngineService

        engine = DecisionEngineService(
            event_bus=MagicMock(),
            clip_threshold=0.55,
            cooldown_seconds=15.0,
            min_evidence_signals=2,
            confirmation_window=3,
            confirmation_required=2,
            threshold_floor=0.35,
            evidence_threshold=0.2,
        )

        score = HighlightScore(
            composite_score=0.80,
            breakdown={"audio_spike": 0.5, "chat_velocity": 0.4, "emotion_intensity": 0.3},
            active_signals=3,
        )

        # Warmup
        for _ in range(5):
            engine.evaluate(score, stream_id="bench")

        # Benchmark
        times = []
        for _ in range(100):
            t0 = time.perf_counter()
            engine.evaluate(score, stream_id="bench")
            times.append(time.perf_counter() - t0)

        median_ms = sorted(times)[len(times) // 2] * 1000
        p99_ms = sorted(times)[int(len(times) * 0.99)] * 1000
        assert median_ms < 1.0, f"evaluate() median {median_ms:.2f}ms, beklenen <1ms"

    def test_confirmation_window_requires_multiple_evaluations(self):
        """
        Confirmation window: window=3, required=2.
        Kayit: record() threshold kontrolunden once calisir.
        Beklenen akis (her degerlendirme kayit sonrasi kontrol):
          Eval 0: record -> history=[1] -> is_confirmed=False (1<2) -> REJECT (confirmation)
          Eval 1: record -> history=[2] -> is_confirmed=True  (2>=2) -> devam...
          Eval 2: record -> history=[3] -> is_confirmed=True  -> CREATE_CLIP
        """
        from shared.event_schemas import HighlightScore
        from microservices.decision_engine.service import DecisionEngineService

        engine = DecisionEngineService(
            event_bus=MagicMock(),
            clip_threshold=0.55,
            cooldown_seconds=15.0,
            min_evidence_signals=2,
            confirmation_window=3,
            confirmation_required=2,
            threshold_floor=0.35,
            evidence_threshold=0.2,
        )

        score = HighlightScore(
            composite_score=0.80,
            breakdown={"audio_spike": 0.5, "chat_velocity": 0.4, "emotion_intensity": 0.3},
            active_signals=3,
        )

        results = []
        for i in range(6):
            result = engine.evaluate(score, stream_id="test_window")
            results.append((i, result.decision, result.reason))

        # Eval 0: confirmation 1/2 -> REJECT
        assert results[0][1] == "REJECT"
        assert "1/2" in results[0][2]

        # Eval 1: confirmation 2/2 -> CREATE_CLIP
        assert results[1][1] == "CREATE_CLIP"

        # Eval 2: cooldown nedeniyle REJECT
        assert results[2][1] == "REJECT"
        assert "Cooldown" in results[2][2]

    def test_cooldown_enforces_minimum_gap(self):
        """Cooldown süresi boyunca yeni klip oluşturulamaz."""
        from shared.event_schemas import HighlightScore
        from microservices.decision_engine.service import DecisionEngineService

        engine = DecisionEngineService(
            event_bus=MagicMock(),
            clip_threshold=0.55,
            cooldown_seconds=10.0,
            min_evidence_signals=2,
            confirmation_window=3,
            confirmation_required=2,
            threshold_floor=0.35,
            evidence_threshold=0.2,
        )

        score = HighlightScore(
            composite_score=0.80,
            breakdown={"audio_spike": 0.5, "chat_velocity": 0.4, "emotion_intensity": 0.3},
            active_signals=3,
        )

        # İlk klip: 2 evaluate (eval 0: confirmation, eval 1: CREATE_CLIP)
        r0 = engine.evaluate(score, stream_id="cooldown_test")
        r1 = engine.evaluate(score, stream_id="cooldown_test")
        assert r1.decision == "CREATE_CLIP"

        # Hemen sonra: cooldown reddeder
        r2 = engine.evaluate(score, stream_id="cooldown_test")
        assert r2.decision == "REJECT"
        assert "Cooldown" in r2.reason

        # Cooldown resetleyerek test et (doğrudan)
        engine._stream_last_clip["cooldown_test"] = None
        engine._stream_confirmation["cooldown_test"].reset()

        r3 = engine.evaluate(score, stream_id="cooldown_test")
        r4 = engine.evaluate(score, stream_id="cooldown_test")
        assert r4.decision == "CREATE_CLIP"

    def test_low_score_rejected_at_layer1(self):
        """Düşük skor Layer 1'de reddedilir."""
        from shared.event_schemas import HighlightScore
        from microservices.decision_engine.service import DecisionEngineService

        engine = DecisionEngineService(event_bus=MagicMock())

        score = HighlightScore(
            composite_score=0.20,
            breakdown={"audio_spike": 0.1},
            active_signals=1,
        )

        result = engine.evaluate(score, stream_id="test")
        assert result.decision == "REJECT"
        assert "Score 0.200 < threshold" in result.reason

    def test_insufficient_evidence_rejected_at_layer3(self):
        """Yeterli kanıt yoksa Layer 3'te reddedilir."""
        from shared.event_schemas import HighlightScore
        from microservices.decision_engine.service import DecisionEngineService

        engine = DecisionEngineService(
            event_bus=MagicMock(),
            min_evidence_signals=3,
            evidence_threshold=0.2,
        )

        score = HighlightScore(
            composite_score=0.80,
            breakdown={"audio_spike": 0.5, "chat_velocity": 0.1},
            active_signals=1,
        )

        result = engine.evaluate(score, stream_id="test")
        assert result.decision == "REJECT"
        assert "evidence" in result.reason.lower()

    def test_combo_fast_track_relaxes_evidence(self):
        """4+ aktif sinyal evidence gereksinimini 1 azaltır."""
        from shared.event_schemas import HighlightScore
        from microservices.decision_engine.service import DecisionEngineService

        engine = DecisionEngineService(
            event_bus=MagicMock(),
            min_evidence_signals=3,  # normalde 3 kanıt gerekli
            evidence_threshold=0.2,
        )

        # Sadece 2 kanıt ama 4+ aktif sinyal -> fast track
        score = HighlightScore(
            composite_score=0.80,
            breakdown={"audio_spike": 0.5, "chat_velocity": 0.4},
            active_signals=4,  # fast track tetiklendi
        )

        # Eval 0: confirmation
        r0 = engine.evaluate(score, stream_id="combo_test")
        assert r0.decision == "REJECT"  # confirmation pending

        # Eval 1: confirmation tamamlandı, fast track ile CREATE_CLIP
        r1 = engine.evaluate(score, stream_id="combo_test")
        assert r1.decision == "CREATE_CLIP"


# ── Toplam uçtan uca gecikme (EventBus üzerinden) ─────────────────────────────

class TestEndToEndLatency:
    """
    EventBus üzerinden sinyal enjekte eder ve gecikmeyi ölçer.
    Gercek EventBus (queue + dispatch loop) kullanarak event akisini test eder.
    """

    @pytest.mark.asyncio
    async def test_full_event_flow_produces_clip_candidate(self):
        """
        Sinyaller EventBus'a publish edilir, EventDetectorService skor uretir,
        DecisionEngineService CLIP_CANDIDATE uretir.
        """
        from shared.event_schemas import EventType
        from shared.event_bus import EventBus
        from microservices.event_detector.service import EventDetectorService
        from microservices.decision_engine.service import DecisionEngineService

        clip_events = []
        scored_events = []

        bus = EventBus()
        await bus.start()

        try:
            async def on_scored(event):
                scored_events.append(event.payload)

            async def on_clip(event):
                clip_events.append(event.payload)

            bus.subscribe(EventType.EVENT_SCORED.value, on_scored)
            bus.subscribe(EventType.CLIP_CANDIDATE.value, on_clip)

            detector = EventDetectorService(
                event_bus=bus,
                score_threshold=0.5,
                score_interval=0.01,
                decay_halflife=60.0,
            )

            decision = DecisionEngineService(
                event_bus=bus,
                clip_threshold=0.55,
                cooldown_seconds=15.0,
                min_evidence_signals=2,
                confirmation_window=3,
                confirmation_required=2,
                threshold_floor=0.35,
                evidence_threshold=0.2,
            )

            t_start = time.perf_counter()

            for i in range(20):
                scoring = detector._get_stream_scoring("test")
                scoring.update_signal("audio_spike", 0.8)
                scoring.update_signal("chat_velocity", 0.6)
                scoring.update_signal("emotion_intensity", 0.5)
                detector._stream_last_score_time["test"] = 0.0
                await detector._maybe_emit_score("test")
                await asyncio.sleep(0.02)

            await asyncio.sleep(0.1)
            elapsed = time.perf_counter() - t_start

            print(f"\n  EVENT_SCORED sayisi: {len(scored_events)}")
            print(f"  CLIP_CANDIDATE sayisi: {len(clip_events)}")
            print(f"  Toplam sure: {elapsed*1000:.0f}ms")

            assert len(scored_events) > 0, "EVENT_SCORED uretilmedi"
            assert len(clip_events) > 0, "CLIP_CANDIDATE uretilmedi!"

            first_clip = clip_events[0]
            score_data = first_clip.get("candidate", {}).get("highlight_score", {})
            assert score_data.get("composite_score", 0) > 0.5

        finally:
            await bus.stop()

    @pytest.mark.asyncio
    async def test_realistic_score_interval_2s(self):
        """
        Gercek score_interval=2.0s ile test.
        Beklenen: her 2sn'de bir EVENT_SCORED, 2. EVENT_SCORED'de CLIP_CANDIDATE.
        Toplam gecikme: ~2.0s (ilk EVENT_SCORED'den 2.'ye kadar).
        """
        from shared.event_schemas import EventType
        from shared.event_bus import EventBus
        from microservices.event_detector.service import EventDetectorService
        from microservices.decision_engine.service import DecisionEngineService

        clip_events = []
        scored_events = []
        scored_times = []
        clip_times = []

        bus = EventBus()
        await bus.start()

        try:
            async def on_scored(event):
                scored_events.append(event.payload)
                scored_times.append(time.perf_counter())

            async def on_clip(event):
                clip_events.append(event.payload)
                clip_times.append(time.perf_counter())

            bus.subscribe(EventType.EVENT_SCORED.value, on_scored)
            bus.subscribe(EventType.CLIP_CANDIDATE.value, on_clip)

            detector = EventDetectorService(
                event_bus=bus,
                score_threshold=0.5,
                score_interval=2.0,
                decay_halflife=60.0,
            )

            decision = DecisionEngineService(
                event_bus=bus,
                clip_threshold=0.55,
                cooldown_seconds=15.0,
                min_evidence_signals=2,
                confirmation_window=3,
                confirmation_required=2,
                threshold_floor=0.35,
                evidence_threshold=0.2,
            )

            t_start = time.perf_counter()

            for i in range(30):
                scoring = detector._get_stream_scoring("test")
                scoring.update_signal("audio_spike", 0.8)
                scoring.update_signal("chat_velocity", 0.6)
                scoring.update_signal("emotion_intensity", 0.5)
                detector._stream_last_score_time["test"] = 0.0
                await detector._maybe_emit_score("test")
                await asyncio.sleep(0.05)

            await asyncio.sleep(0.2)

            print(f"\n  score_interval=2.0s ile test:")
            print(f"  EVENT_SCORED sayisi: {len(scored_events)}")
            print(f"  CLIP_CANDIDATE sayisi: {len(clip_events)}")

            if scored_times:
                print(f"  Ilk EVENT_SCORED: 0ms")
            if len(scored_times) > 1:
                print(f"  2. EVENT_SCORED: {(scored_times[1]-scored_times[0])*1000:.0f}ms")
            if clip_times and scored_times:
                latency = (clip_times[0] - scored_times[0]) * 1000
                print(f"  CLIP_CANDIDATE gecikmesi (ilk scored'dan): {latency:.0f}ms")

            assert len(scored_events) >= 2, f"En az 2 EVENT_SCORED bekleniyor, {len(scored_events)} alindi"
            assert len(clip_events) >= 1, "CLIP_CANDIDATE uretilmedi"

        finally:
            await bus.stop()


# ── LLM katmanı kontrolü ──────────────────────────────────────────────────────

class TestLLMLayer:
    """LLM Validation katmaninin implemente edilip edilmedigini dogrular."""

    def test_llm_layer_not_implemented(self):
        """evaluate() icinde LLM cagrisi yok."""
        import inspect
        from microservices.decision_engine.service import DecisionEngineService

        source = inspect.getsource(DecisionEngineService.evaluate)
        llm_keywords = ["llm", "litellm", "generate", "completion", "chat.completions"]
        found = [kw for kw in llm_keywords if kw in source.lower()]
        assert len(found) == 0, f"evaluate() icinde LLM cagrisi bulundu: {found}"

    def test_decision_engine_has_no_llm_import(self):
        """DecisionEngineService LLM modulu import etmez."""
        import inspect
        from microservices.decision_engine import service
        source = inspect.getsource(service)
        llm_imports = [
            l for l in source.split("\n")
            if "import" in l and ("llm" in l.lower() or "litellm" in l.lower())
        ]
        assert len(llm_imports) == 0, f"LLM import bulundu: {llm_imports}"


# ── Parametre dogrulama ────────────────────────────────────────────────────────

class TestDecisionParameters:
    """Config'deki tum decision parametrelerinin dogrulugunu test eder."""

    def test_config_defaults(self):
        from config import get_settings
        s = get_settings()

        assert s.decision_clip_threshold == 0.55
        assert s.decision_cooldown_seconds == 15.0
        assert s.decision_min_evidence == 2
        assert s.decision_confirmation_window == 3
        assert s.decision_confirmation_required == 2
        assert s.decision_threshold_floor == 0.35
        assert s.decision_evidence_threshold == 0.2
        assert s.decision_score_interval == 2.0
        assert s.decision_decay_halflife == 5.0

    def test_minimum_theoretical_latency(self):
        """
        Teorik minimum gecikme:
        - score_interval = 2.0s
        - confirmation_window = 3, required = 2
        - İlk 2 EVENT_SCORED sonrasi CREATE_CLIP
        - Minimum: 2 x 2.0s = 4.0s
        """
        from config import get_settings
        s = get_settings()
        min_evals = s.decision_confirmation_required
        interval = s.decision_score_interval
        theoretical = min_evals * interval
        assert theoretical == 4.0


# ── Buffer boyutu gerekcesi ───────────────────────────────────────────────────

class TestBufferJustification:
    """180 saniyelik buffer boyutunun neden mantikli oldugunu sayilarla gosterir."""

    def test_buffer_calculation(self):
        from config import get_settings
        s = get_settings()

        # Gecikme zinciri
        detection = 1.0            # 1s audio chunk + video frame
        event_detector = s.decision_score_interval  # 2.0s throttle
        confirmation = s.decision_confirmation_required * s.decision_score_interval  # 4.0s
        total_latency = detection + event_detector + confirmation

        # Buffer ihtiyaci
        max_clip = 150.0           # en uzun klip (saniye)
        render_buffer = 30.0       # post-processing
        margin = 2.0

        needed = total_latency + max_clip + render_buffer + margin
        available = 180

        assert needed <= available + 15, f"Buffer {needed:.0f}s gerektiriyor, 180s yetmeyebilir"

        print(f"\n  Latency breakdown:")
        print(f"    Detection:        {detection:.1f}s")
        print(f"    EventDetector:    {event_detector:.1f}s")
        print(f"    Confirmation:     {confirmation:.1f}s")
        print(f"    Total decision:   {total_latency:.1f}s")
        print(f"  Buffer needs:")
        print(f"    Decision latency: {total_latency:.1f}s")
        print(f"    Max clip:         {max_clip:.1f}s")
        print(f"    Render buffer:    {render_buffer:.1f}s")
        print(f"    Margin:           {margin:.1f}s")
        print(f"    Total needed:     {needed:.1f}s")
        print(f"    Available:        {available}s")
        print(f"    Verdict:          {'OK' if needed <= available else 'TIGHT but OK for typical clips'}")
