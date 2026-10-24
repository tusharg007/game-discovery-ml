from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def jensen_shannon_divergence(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("histograms must have the same nonzero number of bins")
    p, q = np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64)
    if np.any(p < 0) or np.any(q < 0) or p.sum() <= 0 or q.sum() <= 0:
        raise ValueError("histograms must be nonnegative and have positive mass")
    p, q = p / p.sum(), q / q.sum()
    midpoint = (p + q) / 2
    p_mask, q_mask = p > 0, q > 0
    divergence = (
        np.sum(p[p_mask] * np.log2(p[p_mask] / midpoint[p_mask]))
        + np.sum(q[q_mask] * np.log2(q[q_mask] / midpoint[q_mask]))
    ) / 2
    return float(divergence)


def compare_profiles(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    if baseline.get("event_stream") != current.get("event_stream"):
        raise ValueError("monitoring profiles from different streams cannot be compared")
    if baseline.get("sample_count", 0) < 100 or current.get("sample_count", 0) < 100:
        raise ValueError("monitoring profiles need at least 100 samples")
    unknown_delta = float(current["unknown_item_ratio"]) - float(baseline["unknown_item_ratio"])
    fallback_ratio = float(current["fallback_rate"]) / max(float(baseline["fallback_rate"]), 1e-9)
    score_js = jensen_shannon_divergence(baseline["score_histogram"], current["score_histogram"])
    popularity_js = jensen_shannon_divergence(
        baseline["popularity_exposure_histogram"],
        current["popularity_exposure_histogram"],
    )
    alerts = []
    if unknown_delta >= 0.05:
        alerts.append("unknown_item_ratio_increased_by_5pp")
    if baseline["fallback_rate"] * baseline["sample_count"] >= 20 and fallback_ratio >= 2.0:
        alerts.append("fallback_rate_doubled_with_minimum_baseline")
    if score_js >= 0.10:
        alerts.append("score_distribution_jsd_over_threshold")
    if popularity_js >= 0.10:
        alerts.append("popularity_exposure_jsd_over_threshold")
    return {
        "event_stream": baseline["event_stream"],
        "baseline_sample_count": baseline["sample_count"],
        "current_sample_count": current["sample_count"],
        "unknown_item_ratio_delta": unknown_delta,
        "fallback_rate_ratio": fallback_ratio,
        "score_histogram_js_divergence_bits": score_js,
        "popularity_exposure_js_divergence_bits": popularity_js,
        "thresholds": {
            "unknown_item_ratio_delta": 0.05,
            "fallback_rate_ratio": 2.0,
            "fallback_minimum_baseline_events": 20,
            "score_histogram_js_divergence_bits": 0.10,
            "popularity_exposure_js_divergence_bits": 0.10,
        },
        "alerts": alerts,
        "alerted": bool(alerts),
    }


def run_monitor_replay(scenario: str, output_path: Path) -> dict[str, Any]:
    """Create an isolated synthetic replay; it never reads or modifies real demo events."""
    baseline = {
        "event_stream": "synthetic_test",
        "sample_count": 1000,
        "unknown_item_ratio": 0.01,
        "fallback_rate": 0.03,
        "score_histogram": [0.55, 0.30, 0.15],
        "popularity_exposure_histogram": [0.70, 0.20, 0.10],
    }
    current = dict(baseline)
    if scenario == "unknown-item-shift":
        current["unknown_item_ratio"] = 0.08
    elif scenario == "fallback-rate-shift":
        current["fallback_rate"] = 0.08
    elif scenario == "score-shift":
        current["score_histogram"] = [0.15, 0.25, 0.60]
    elif scenario == "popularity-shift":
        current["popularity_exposure_histogram"] = [0.25, 0.30, 0.45]
    elif scenario != "stable-control":
        raise ValueError(f"unsupported monitoring replay scenario: {scenario}")
    report = {
        "scenario": scenario,
        "data_source": "generated fixture only; no real-demo events read",
        "baseline": baseline,
        "current": current,
        "result": compare_profiles(baseline, current),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
