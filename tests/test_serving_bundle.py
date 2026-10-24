from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import scipy.sparse as sp

from game_discovery.evaluation.final_test import evaluate_frozen_candidate_on_test
from game_discovery.serving.bundle import RecommendationBundle, export_selected_bundle


def _write_bundle(directory: Path) -> RecommendationBundle:
    directory.mkdir(parents=True)
    features_path = directory / "features.npz"
    catalog_path = directory / "catalog.json"
    sp.save_npz(
        features_path,
        sp.csr_matrix(np.asarray([[1, 0], [0.9, 0.1], [0, 1]], dtype=np.float32)),
    )
    catalog = [
        {
            "item_id": "1",
            "title": "Action One",
            "genres": ["Action"],
            "tags": ["Adventure"],
            "release_date": None,
            "metadata_missing": False,
            "training_interactions": 8,
            "recent_30d_interactions": 1,
        },
        {
            "item_id": "2",
            "title": "Action Two",
            "genres": ["Action"],
            "tags": ["Adventure"],
            "release_date": None,
            "metadata_missing": False,
            "training_interactions": 3,
            "recent_30d_interactions": 5,
        },
        {
            "item_id": "3",
            "title": "Puzzle Three",
            "genres": ["Puzzle"],
            "tags": ["Logic"],
            "release_date": None,
            "metadata_missing": False,
            "training_interactions": 2,
            "recent_30d_interactions": 9,
        },
    ]
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    manifest = {
        "model_version": "fixture-v1",
        "features_file": features_path.name,
        "features_sha256": hashlib.sha256(features_path.read_bytes()).hexdigest(),
        "catalog_file": catalog_path.name,
        "catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "content_rank_weight": 0.1,
    }
    (directory / "release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return RecommendationBundle(directory)


def test_bundle_excludes_seeds_and_exclusions_and_explains_shared_attributes(tmp_path: Path):
    bundle = _write_bundle(tmp_path / "bundle")
    result = bundle.recommend(["1", "1", "unknown"], exclude_item_ids=["2"], k=10)
    assert [row["item_id"] for row in result["recommendations"]] == ["3"]
    assert "1" not in {row["item_id"] for row in result["recommendations"]}
    assert result["duplicate_seed_count"] == 1
    assert result["unknown_seed_count"] == 1
    assert result["fallback_reason"] == "unknown_seeds_used_known_content"


def test_bundle_uses_popularity_when_no_known_seed_and_validates_k(tmp_path: Path):
    bundle = _write_bundle(tmp_path / "bundle")
    result = bundle.recommend([], k=2)
    assert [row["item_id"] for row in result["recommendations"]] == ["3", "2"]
    assert result["model"] == "recent30_popularity_fallback"
    with pytest.raises(ValueError):
        bundle.recommend([], k=21)
    with pytest.raises(ValueError):
        bundle.recommend(["1"] * 21)


def test_bundle_unknown_only_and_all_excluded_fallbacks(tmp_path: Path):
    bundle = _write_bundle(tmp_path / "bundle")
    unknown = bundle.recommend(["not-in-catalog"], k=2)
    assert unknown["model"] == "recent30_popularity_fallback"
    assert unknown["fallback_reason"] == "no_known_seed_games"
    assert unknown["unknown_seed_count"] == 1
    exhausted = bundle.recommend(["1"], exclude_item_ids=["2", "3"], k=2)
    assert exhausted["recommendations"] == []
    assert exhausted["fallback_reason"] == "all_candidates_excluded"


def test_bundle_rejects_corrupt_catalog_hash(tmp_path: Path):
    directory = tmp_path / "bundle"
    _write_bundle(directory)
    catalog_path = directory / "catalog.json"
    catalog_path.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="catalog hash mismatch"):
        RecommendationBundle(directory)


def test_final_test_evaluator_uses_refit_item_only_bundle(tmp_path: Path):
    split_dir = tmp_path / "splits"
    split_dir.mkdir()
    rows_by_split = {
        "train": [
            {"user_key": "u1", "item_id": "i1", "event_date": date(2017, 1, 1)},
            {"user_key": "u1", "item_id": "i2", "event_date": date(2017, 1, 2)},
            {"user_key": "u2", "item_id": "i3", "event_date": date(2017, 1, 3)},
        ],
        "validation": [{"user_key": "u3", "item_id": "i1", "event_date": date(2017, 2, 1)}],
        "test": [{"user_key": "u1", "item_id": "i3", "event_date": date(2017, 3, 1)}],
    }
    partition_evidence = {}
    for name, rows in rows_by_split.items():
        path = split_dir / f"{name}.parquet"
        pq.write_table(pa.Table.from_pylist(rows), path)
        partition_evidence[name] = {
            "parquet_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "last_date": rows[-1]["event_date"].isoformat(),
        }
    manifest_path = tmp_path / "split.json"
    manifest_path.write_text(
        json.dumps(
            {
                "split_manifest_sha256": "synthetic-split",
                "cutoff_a": "2017-02-01",
                "cutoff_b": "2017-03-01",
                "partitions": partition_evidence,
            }
        ),
        encoding="utf-8",
    )
    metadata_path = tmp_path / "items.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "item_id": item,
                    "title": f"Action {item}",
                    "genres": ["Action"],
                    "tags": ["space"],
                    "release_date": None,
                    "metadata_missing": False,
                }
                for item in ("i1", "i2", "i3")
            ]
        ),
        metadata_path,
    )
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(
        json.dumps(
            {
                "split_manifest_sha256": "synthetic-split",
                "selected_candidate": "hybrid_recent30_content_w10",
                "parameters": {
                    "tfidf_ngram_range": [1, 2],
                    "tfidf_min_df": 2,
                    "tfidf_max_features": 100,
                    "content_rank_weight": 0.1,
                    "recent_popularity_days": 30,
                },
            }
        ),
        encoding="utf-8",
    )
    bundle_dir = tmp_path / "bundle"
    export_selected_bundle(split_dir, metadata_path, selection_path, manifest_path, bundle_dir)
    result = evaluate_frozen_candidate_on_test(
        split_dir,
        manifest_path,
        selection_path,
        bundle_dir,
        tmp_path / "reports/test.json",
        tmp_path / "private/test.parquet",
    )
    assert result["evaluation_split"] == "test"
    assert result["warm_catalog_users"] == 1
    assert result["candidate"]["warm_catalog_ranking"]["mean_ndcg@10"] == 1.0
