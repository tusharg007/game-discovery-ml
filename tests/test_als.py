from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from game_discovery.models.als import ALS_GRID, ALSConfig, build_confidence_matrix, train_als_grid
from game_discovery.serving.als import ALSComparisonModel


def test_confidence_matrix_uses_explicit_one_plus_alpha():
    matrix = build_confidence_matrix(
        np.array([0, 1], dtype=np.int32),
        np.array([1, 0], dtype=np.int32),
        2,
        2,
        confidence_alpha=10,
    )
    assert matrix.nnz == 2
    assert matrix[0, 1] == 11
    assert matrix[1, 0] == 11
    assert matrix[0, 0] == 0
    assert len(ALS_GRID) == 8
    with pytest.raises(ValueError):
        build_confidence_matrix(np.array([0]), np.array([0]), 1, 1, confidence_alpha=0)


def test_implicit_cpu_als_training_smoke_records_factors_and_runtime(tmp_path: Path):
    train_path = tmp_path / "train.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"user_key": "u1", "item_id": "i1"},
                {"user_key": "u1", "item_id": "i2"},
                {"user_key": "u2", "item_id": "i1"},
                {"user_key": "u3", "item_id": "i3"},
            ]
        ),
        train_path,
    )
    digest = hashlib.sha256(train_path.read_bytes()).hexdigest()
    split_manifest = tmp_path / "split_manifest.json"
    split_manifest.write_text(
        json.dumps(
            {
                "split_manifest_sha256": "fixture-manifest",
                "partitions": {"train": {"parquet_sha256": digest}},
            }
        ),
        encoding="utf-8",
    )
    result = train_als_grid(
        train_path,
        split_manifest,
        tmp_path / "private/models",
        tmp_path / "artifacts/als_training.json",
        configs=(ALSConfig(2, 0.1, 1.0, iterations=2, seed=9),),
    )
    assert result["configuration_count"] == 1
    config = result["configurations"][0]
    assert config["device"] == "cpu"
    assert config["library_alpha_multiplier"] == 1.0
    assert config["stored_observed_confidence"] == 2.0
    assert config["runtime_seconds"] > 0
    assert config["fit_input_nnz"] == 4
    with np.load(config["private_factors_path"], allow_pickle=False) as arrays:
        assert arrays["item_factors"].shape == (3, 2)
        assert arrays["user_factors"].shape == (3, 2)


def test_als_serving_filters_genres_before_truncating_candidates(tmp_path: Path):
    directory = tmp_path / "als-sidecar"
    directory.mkdir()
    factors_path = directory / "item_factors.npz"
    index_path = directory / "item_ids.json"
    np.savez_compressed(
        factors_path,
        item_factors=np.asarray([[1, 0], [0, 1], [1, 1]], dtype=np.float32),
    )
    index_path.write_text(json.dumps(["1", "2", "3"]), encoding="utf-8")
    manifest = {
        "item_factors_file": factors_path.name,
        "item_factors_sha256": hashlib.sha256(factors_path.read_bytes()).hexdigest(),
        "item_ids_file": index_path.name,
        "item_ids_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "regularization": 0.1,
        "confidence": 2.0,
        "source_configuration": "fixture-als",
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    model = ALSComparisonModel(directory)
    result = model.recommend(["1"], allowed_item_ids={"3"}, k=1)
    assert [row["item_id"] for row in result["recommendations"]] == ["3"]
    no_match = model.recommend(["1"], allowed_item_ids=set(), k=1)
    assert no_match["fallback_reason"] == "no_candidates_match_filter"
