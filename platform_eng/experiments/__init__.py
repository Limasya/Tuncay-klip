"""platform_eng.experiments — A/B test bucketing + anlamlılık (IP_PART6 37.4-37.6)."""
from platform_eng.experiments.ab import (
    assign_variant,
    evaluate_ab,
    required_sample_size,
    AbResult,
)

__all__ = [
    "assign_variant",
    "evaluate_ab",
    "required_sample_size",
    "AbResult",
]
