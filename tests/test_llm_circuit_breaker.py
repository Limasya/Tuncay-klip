"""
Tests for Circuit Breaker pattern in LLM engine.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from services.llm_engine import CircuitBreaker


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        assert cb.state == "closed"
        assert cb.can_try() is True

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"
        assert cb.can_try() is False

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        assert cb.can_try() is True

    def test_resets_on_success(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"
        cb.record_success()
        assert cb.state == "closed"
        assert cb.can_try() is True

    def test_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.05)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"
        cb._last_failure_time -= 0.1
        assert cb.state == "half_open"
        assert cb.can_try() is True

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)
        for _ in range(2):
            cb.record_failure()
        assert cb.state == "open"
        cb._last_failure_time -= 0.1
        assert cb.state == "half_open"
        cb.record_failure()
        assert cb.state == "open"

    def test_many_successes_no_open(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        for _ in range(100):
            cb.record_success()
        assert cb.state == "closed"

    def test_alternating_success_failure(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_success()
        assert cb.state == "closed"


@pytest.mark.asyncio
async def test_circuit_breaker_skips_open_provider():
    """LLMEngine skips a provider whose circuit breaker is already OPEN."""
    from services.llm_engine import LLMEngine, CircuitBreaker

    engine = LLMEngine()
    provider_name = "test_failer"
    call_count = 0

    async def failing_provider(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("simulated failure")

    engine._circuit_breakers[provider_name] = CircuitBreaker(
        failure_threshold=1, recovery_timeout=60.0
    )
    engine._providers.insert(0, (provider_name, failing_provider))

    result = await engine.generate("test prompt", use_cache=False)
    assert call_count == 1, "First call should try the provider once before opening"
    assert engine._circuit_breakers[provider_name].state == "open", "CB should be open after 1 failure"

    result2 = await engine.generate("test prompt 2", use_cache=False)
    assert call_count == 1, "Second call should skip the open provider"
    assert len(result2) > 0, "Should return fallback content"


@pytest.mark.asyncio
async def test_circuit_breaker_recovers_with_half_open():
    """Half-open provider succeeds -> CB resets to closed."""
    from services.llm_engine import LLMEngine, CircuitBreaker

    engine = LLMEngine()
    provider_name = "test_recoverer"
    call_count = 0

    async def recoverable_provider(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        return "recovered ok"

    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
    cb._state = "half_open"
    cb._failure_count = 1
    engine._circuit_breakers[provider_name] = cb
    engine._providers.insert(0, (provider_name, recoverable_provider))

    result = await engine.generate("test prompt", use_cache=False)
    assert call_count == 1
    assert result == "recovered ok"
    assert cb.state == "closed"
