from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import scipy.sparse as sp

from game_discovery.evaluation.hybrid import _rank_fusion
from game_discovery.models.content import train_static_metadata_tfidf
from game_discovery.models.item_item import train_item_item


def _fixture_split(tmp_path: Path) -> tuple[Path, Path]:
    train_path = tmp_path / "train.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"user_key": "u1", "item_id": "i1"},
                {"user_key": "u1", "item_id": "i2"},
                {"user_key": "u2", "item_id": "i1"},
                {"user_key": "u2", "item_id": "i3"},
                {"user_key": "u3", "item_id": "i2"},
            ]
        ),
        train_path,
    )
    digest = hashlib.sha256(train_path.read_bytes()).hexdigest()
    manifest_path = tmp_path / "split_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "split_manifest_sha256": "fixture-manifest",
                "partitions": {"train": {"parquet_sha256": digest}},
            }
        ),
        encoding="utf-8",
    )
    return train_path, manifest_path


def test_item_item_training_writes_sparse_shrunk_neighbors(tmp_path: Path):
    train_path, manifest_path = _fixture_split(tmp_path)
    report = train_item_item(
        train_path,
        manifest_path,
        tmp_path / "private/item_similarity.npz",
        tmp_path / "reports/item_item.json",
        shrinkage=1.0,
        max_neighbors=2,
    )
    matrix = sp.load_npz(report["similarity_path"])
    assert report["training_event_count"] == 5
    assert report["similarity_nnz"] == matrix.nnz
    assert matrix.shape == (3, 3)
    assert matrix.diagonal().sum() == 0
    assert matrix.nnz <= 6


def test_static_metadata_features_are_sparse_and_catalog_aligned(tmp_path: Path):
    train_path, manifest_path = _fixture_split(tmp_path)
    items_path = tmp_path / "items.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "item_id": "i1",
                    "title": "Action Orbit",
                    "genres": ["Action"],
                    "tags": ["space"],
                },
                {
                    "item_id": "i2",
                    "title": "Action Station",
                    "genres": ["Action"],
                    "tags": ["strategy"],
                },
                {
                    "item_id": "i3",
                    "title": "Quiet Garden",
                    "genres": ["Puzzle"],
                    "tags": ["relaxing"],
                },
            ]
        ),
        items_path,
    )
    report = train_static_metadata_tfidf(
        train_path,
        items_path,
        manifest_path,
        tmp_path / "private/content.npz",
        tmp_path / "reports/content.json",
    )
    matrix = sp.load_npz(report["similarity_path"])
    assert report["catalog_item_count"] == 3
    assert report["missing_metadata_count"] == 0
    assert matrix.shape[0] == 3
    assert matrix.nnz > 0


def test_rank_fusion_excludes_seen_candidates_and_breaks_ties_by_item_id():
    items = np.asarray(["a", "b", "c", "d"])
    candidates = np.asarray([1, 2, 3], dtype=np.int32)
    popularity_order = np.asarray([0, 1, 2, 3], dtype=np.int32)
    scores = np.asarray([100.0, 0.0, 0.0, 1.0])
    ranked = _rank_fusion(items, candidates, popularity_order, scores, 0.5, 3)
    assert "a" not in ranked
    assert len(ranked) == len(set(ranked)) == 3
    assert ranked.index("b") < ranked.index("c")
