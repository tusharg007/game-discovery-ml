from __future__ import annotations

import math

import pytest

from game_discovery.evaluation.bootstrap import paired_user_bootstrap_difference
from game_discovery.evaluation.ranking import ranking_metrics, top_unseen_items


def test_ranking_metrics_match_hand_calculation():
    result = ranking_metrics(["a", "b", "c"], {"b", "c", "unreachable"}, (1, 2, 3))
    assert result["recall@1"] == 0
    assert result["hit_rate@1"] == 0
    assert result["recall@2"] == pytest.approx(1 / 3)
    assert result["hit_rate@2"] == 1
    assert result["ndcg@2"] == pytest.approx((1 / math.log2(3)) / (1 + 1 / math.log2(3)))
    assert result["recall@3"] == pytest.approx(2 / 3)


def test_unseen_ranking_deduplicates_and_excludes_history():
    assert top_unseen_items(["s", "a", "a", "b"], {"s"}, 3) == ["a", "b"]
    with pytest.raises(ValueError):
        top_unseen_items(["a"], set(), 0)
    with pytest.raises(ValueError):
        ranking_metrics(["a", "a"], {"a"})


def test_paired_bootstrap_preserves_user_level_difference_and_seed():
    result = paired_user_bootstrap_difference([0.1, 0.2], [0.2, 0.3], resamples=100, seed=9)
    assert result["mean_difference"] == pytest.approx(0.1)
    assert result["ci95_low"] == pytest.approx(0.1)
    assert result["ci95_high"] == pytest.approx(0.1)
    assert result["users"] == 2
