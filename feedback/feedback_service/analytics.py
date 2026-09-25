"""Small statistical helpers shared by aggregate chart renderers."""

from __future__ import annotations

import math


def wilson_interval(successes: int, total: int, *, z_score: float = 1.96) -> tuple[float, float]:
    """Return a Wilson score interval as percentages."""

    if total <= 0 or successes < 0 or successes > total:
        return (0.0, 0.0)
    proportion = successes / total
    denominator = 1 + (z_score**2 / total)
    centre = (proportion + z_score**2 / (2 * total)) / denominator
    margin = (
        z_score
        * math.sqrt(
            (proportion * (1 - proportion) / total)
            + (z_score**2 / (4 * total**2))
        )
        / denominator
    )
    return (max(0.0, (centre - margin) * 100), min(100.0, (centre + margin) * 100))
