from __future__ import annotations

import numpy as np


def paired_user_bootstrap_difference(
    baseline: list[float],
    candidate: list[float],
    *,
    resamples: int = 2_000,
    seed: int = 1_729,
) -> dict[str, float | int]:
    if len(baseline) != len(candidate) or not baseline:
        raise ValueError("Paired bootstrap inputs must have the same non-zero user count")
    if resamples < 1:
        raise ValueError("resamples must be positive")
    difference = np.asarray(candidate, dtype=np.float64) - np.asarray(baseline, dtype=np.float64)
    if not np.isfinite(difference).all():
        raise ValueError("Bootstrap metric contributions must be finite")
    rng = np.random.default_rng(seed)
    indexes = rng.integers(0, len(difference), size=(resamples, len(difference)), dtype=np.int32)
    means = difference[indexes].mean(axis=1)
    lower, upper = np.quantile(means, (0.025, 0.975), method="linear")
    return {
        "users": len(difference),
        "resamples": resamples,
        "seed": seed,
        "mean_difference": float(difference.mean()),
        "ci95_low": float(lower),
        "ci95_high": float(upper),
    }
