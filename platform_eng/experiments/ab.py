"""
A/B test yardımcıları (IP_PART6 Bölüm 37.4-37.6).

- assign_variant: deterministik, stabil kova ataması (aynı birim → aynı varyant).
- evaluate_ab: iki-oranlı z-testi ile istatistiksel anlamlılık.
- required_sample_size: kol başına gereken örneklem büyüklüğü (güç analizi).

scipy varsa onun norm dağılımı; yoksa math.erf tabanlı normal CDF kullanılır
(harici bağımlılık zorunlu değildir).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass


def _norm_cdf(x: float) -> float:
    """Standart normal kümülatif dağılım (scipy varsa onu kullanır)."""
    try:
        from scipy import stats

        return float(stats.norm.cdf(x))
    except Exception:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Standart normal ters CDF (quantile). scipy varsa onu kullanır."""
    try:
        from scipy import stats

        return float(stats.norm.ppf(p))
    except Exception:
        # Acklam (1998) rasyonel yaklaşımı — yeterli hassasiyet
        a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
             1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
        b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
             6.680131188771972e+01, -1.328068155288572e+01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
             -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
        d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
             3.754408661907416e+00]
        plow, phigh = 0.02425, 1 - 0.02425
        if p < plow:
            q = math.sqrt(-2 * math.log(p))
            return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                   ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        if p > phigh:
            q = math.sqrt(-2 * math.log(1 - p))
            return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                    ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def assign_variant(experiment: str, unit_id: str, weights: dict[str, int]) -> str:
    """
    Deterministik varyant ataması (IP_PART6 37.5).

    Aynı (experiment, unit_id) her zaman aynı varyanta düşer. weights ağırlıkları
    100'e tamamlanmalıdır (örn. {"control": 50, "treatment": 50}).
    """
    digest = hashlib.sha256(f"{experiment}:{unit_id}".encode()).hexdigest()
    bucket = int(digest[:8], 16) % 100  # 0..99
    cumulative = 0
    for variant, weight in weights.items():
        cumulative += weight
        if bucket < cumulative:
            return variant
    # ağırlıklar 100'ü tamamlamıyorsa son varyanta düş
    return next(reversed(weights)) if weights else "control"


@dataclass
class AbResult:
    """İki-oranlı A/B test sonucu."""

    rate_a: float
    rate_b: float
    lift: float          # (p_b - p_a) / p_a
    z_score: float
    p_value: float
    significant: bool
    winner: str          # "treatment" | "control" | "no_change"


def evaluate_ab(
    conv_a: int,
    n_a: int,
    conv_b: int,
    n_b: int,
    alpha: float = 0.05,
) -> AbResult:
    """
    İki-oranlı z-testi (IP_PART6 37.6).

    Args:
        conv_a/n_a: kontrol kolunun dönüşüm/örneklem sayısı.
        conv_b/n_b: treatment kolunun dönüşüm/örneklem sayısı.
        alpha: anlamlılık seviyesi (varsayılan 0.05, çift taraflı).
    """
    if n_a <= 0 or n_b <= 0:
        raise ValueError("örneklem büyüklükleri pozitif olmalı")

    p_a, p_b = conv_a / n_a, conv_b / n_b
    p_pool = (conv_a + conv_b) / (n_a + n_b)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))

    if se == 0:
        z = 0.0
        p_value = 1.0
    else:
        z = (p_b - p_a) / se
        p_value = 2 * (1 - _norm_cdf(abs(z)))

    significant = p_value < alpha
    lift = (p_b - p_a) / p_a if p_a > 0 else float("inf") if p_b > 0 else 0.0
    if significant:
        winner = "treatment" if p_b > p_a else "control"
    else:
        winner = "no_change"

    return AbResult(
        rate_a=p_a,
        rate_b=p_b,
        lift=lift,
        z_score=z,
        p_value=p_value,
        significant=significant,
        winner=winner,
    )


def required_sample_size(
    baseline_rate: float,
    min_detectable_effect: float,
    alpha: float = 0.05,
    power: float = 0.8,
) -> int:
    """
    Kol başına gereken örneklem büyüklüğü (IP_PART6 37.4 — güç analizi).

    Args:
        baseline_rate: kontrol dönüşüm oranı (0..1).
        min_detectable_effect: mutlak tespit edilebilir fark (örn. 0.03 = +3pp).
        alpha: yanlış pozitif oranı (çift taraflı).
        power: 1 - beta (varsayılan 0.8).
    """
    if not 0 < baseline_rate < 1:
        raise ValueError("baseline_rate 0 ile 1 arasında olmalı")
    if min_detectable_effect <= 0:
        raise ValueError("min_detectable_effect pozitif olmalı")

    p1 = baseline_rate
    p2 = min(max(baseline_rate + min_detectable_effect, 1e-9), 1 - 1e-9)
    z_alpha = _norm_ppf(1 - alpha / 2)
    z_beta = _norm_ppf(power)
    p_bar = (p1 + p2) / 2

    numerator = (
        z_alpha * math.sqrt(2 * p_bar * (1 - p_bar))
        + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    ) ** 2
    n = numerator / ((p2 - p1) ** 2)
    return math.ceil(n)
