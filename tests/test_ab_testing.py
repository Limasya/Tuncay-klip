"""
platform_eng.experiments testleri (IP_PART6 Bölüm 37.4-37.6).

Kapsam:
  - assign_variant: deterministik, stabil, ağırlıklara uygun dağılım
  - evaluate_ab: iki-oranlı z-testi (anlamlı / anlamsız / kazanan)
  - required_sample_size: güç analizi + doğrulama
"""
import pytest

from platform_eng.experiments import assign_variant, evaluate_ab, required_sample_size


# ── assign_variant ────────────────────────────────────────────────────
def test_assign_variant_is_deterministic():
    weights = {"control": 50, "treatment": 50}
    v = assign_variant("exp1", "user-1", weights)
    for _ in range(20):
        assert assign_variant("exp1", "user-1", weights) == v
    assert v in weights


def test_assign_variant_distribution():
    weights = {"control": 50, "treatment": 50}
    counts = {"control": 0, "treatment": 0}
    for i in range(4000):
        counts[assign_variant("exp-dist", f"user-{i}", weights)] += 1
    ratio = counts["treatment"] / 4000
    assert 0.45 < ratio < 0.55


def test_assign_variant_respects_weights():
    weights = {"control": 90, "treatment": 10}
    counts = {"control": 0, "treatment": 0}
    for i in range(4000):
        counts[assign_variant("exp-weight", f"user-{i}", weights)] += 1
    ratio = counts["treatment"] / 4000
    assert 0.05 < ratio < 0.15


# ── evaluate_ab ───────────────────────────────────────────────────────
def test_evaluate_ab_detects_significant_lift():
    # kontrol %10, treatment %15, büyük örneklem => anlamlı
    result = evaluate_ab(conv_a=1000, n_a=10000, conv_b=1500, n_b=10000)
    assert result.significant is True
    assert result.winner == "treatment"
    assert result.lift > 0


def test_evaluate_ab_no_significant_difference():
    result = evaluate_ab(conv_a=100, n_a=1000, conv_b=105, n_b=1000)
    assert result.significant is False
    assert result.winner == "no_change"


def test_evaluate_ab_identical_rates_pvalue_one():
    result = evaluate_ab(conv_a=100, n_a=1000, conv_b=100, n_b=1000)
    assert result.p_value == pytest.approx(1.0, abs=1e-9)
    assert result.significant is False


def test_evaluate_ab_invalid_sample_raises():
    with pytest.raises(ValueError):
        evaluate_ab(conv_a=1, n_a=0, conv_b=1, n_b=10)


# ── required_sample_size ──────────────────────────────────────────────
def test_required_sample_size_positive_and_monotone():
    big_effect = required_sample_size(0.10, 0.05)
    small_effect = required_sample_size(0.10, 0.01)
    assert big_effect > 0
    # daha küçük etki => daha büyük örneklem gerekir
    assert small_effect > big_effect


def test_required_sample_size_validates_inputs():
    with pytest.raises(ValueError):
        required_sample_size(0.0, 0.05)
    with pytest.raises(ValueError):
        required_sample_size(0.1, 0.0)
