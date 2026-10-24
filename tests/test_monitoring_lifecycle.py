from __future__ import annotations

from pathlib import Path

import pytest

from game_discovery.monitoring.drift import compare_profiles, run_monitor_replay
from game_discovery.monitoring.promotion import PromotionLedger, evaluate_promotion_gate


def test_replay_detects_popularity_shift_and_stable_control_is_quiet(tmp_path: Path):
    shifted = run_monitor_replay("popularity-shift", tmp_path / "shift.json")
    stable = run_monitor_replay("stable-control", tmp_path / "stable.json")
    assert shifted["result"]["event_stream"] == "synthetic_test"
    assert "popularity_exposure_jsd_over_threshold" in shifted["result"]["alerts"]
    assert stable["result"]["alerted"] is False
    assert (tmp_path / "shift.json").is_file()


@pytest.mark.parametrize(
    ("scenario", "alert"),
    [
        ("unknown-item-shift", "unknown_item_ratio_increased_by_5pp"),
        ("fallback-rate-shift", "fallback_rate_doubled_with_minimum_baseline"),
        ("score-shift", "score_distribution_jsd_over_threshold"),
    ],
)
def test_monitor_replay_detects_each_shift_family(tmp_path: Path, scenario: str, alert: str):
    report = run_monitor_replay(scenario, tmp_path / f"{scenario}.json")
    assert alert in report["result"]["alerts"]


def test_monitor_rejects_small_samples_and_mixed_streams():
    profile = {
        "event_stream": "replay",
        "sample_count": 99,
        "unknown_item_ratio": 0.01,
        "fallback_rate": 0.01,
        "score_histogram": [1, 1],
        "popularity_exposure_histogram": [1, 1],
    }
    with pytest.raises(ValueError, match="100 samples"):
        compare_profiles(profile, {**profile, "sample_count": 100})
    with pytest.raises(ValueError, match="different streams"):
        compare_profiles({**profile, "sample_count": 100}, {**profile, "event_stream": "real_demo"})


def test_promotion_gate_rejects_regression_and_ledger_rolls_back(tmp_path: Path):
    ledger_dir = tmp_path / "lifecycle"
    champion = ledger_dir / "artifacts" / "champion.bin"
    rejected = ledger_dir / "artifacts" / "rejected.bin"
    accepted = ledger_dir / "artifacts" / "candidate.bin"
    for path, content in (
        (champion, b"champion"),
        (rejected, b"regression"),
        (accepted, b"candidate"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    metrics = {"mean_ndcg@10": 1.0}
    assert evaluate_promotion_gate(metrics, {"mean_ndcg@10": 0.97})["accepted"] is False
    ledger = PromotionLedger(ledger_dir)
    ledger.initialize("champion-v1", champion)
    rejection = ledger.promote("rejected-v2", rejected, metrics, {"mean_ndcg@10": 0.97})
    assert rejection["active_version"] == "champion-v1"
    assert ledger.read()["rejected_candidates"][0]["artifact_path"] == "artifacts/rejected.bin"
    promotion = ledger.promote("candidate-v2", accepted, metrics, {"mean_ndcg@10": 1.01})
    assert promotion["active_version"] == "candidate-v2"
    rollback = ledger.rollback("champion-v1")
    assert rollback["active_version"] == "champion-v1"
    assert ledger.read()["history"] == ["champion-v1", "candidate-v2"]


def test_promotion_ledger_rejects_external_paths_and_detects_artifact_changes(tmp_path: Path):
    root = tmp_path / "registry"
    ledger = PromotionLedger(root)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"external")
    with pytest.raises(ValueError, match="inside the ledger"):
        ledger.initialize("champion-v1", outside)
    artifact = root / "champion.bin"
    artifact.write_bytes(b"original")
    ledger.initialize("champion-v1", artifact)
    artifact.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="hash does not match"):
        ledger.rollback("champion-v1")
