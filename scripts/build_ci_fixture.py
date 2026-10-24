"""Create an explicitly synthetic, disposable bundle for container smoke tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import scipy.sparse as sp

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if os.environ.get("GAME_DISCOVERY_CI_FIXTURE") != "1":
        raise SystemExit("Set GAME_DISCOVERY_CI_FIXTURE=1 in an isolated CI checkout only.")
    bundle = ROOT / "models/release/selected_candidate"
    als = ROOT / "models/release/alternates/als"
    reports = ROOT / "artifacts/reports"
    bundle.mkdir(parents=True, exist_ok=True)
    als.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    features_path = bundle / "content_features.npz"
    catalog_path = bundle / "catalog.json"
    catalog = [
        {
            "item_id": "1",
            "title": "Fixture Action",
            "genres": ["Action"],
            "tags": ["Adventure"],
            "release_date": None,
            "metadata_missing": False,
            "training_interactions": 8,
            "recent_30d_interactions": 1,
        },
        {
            "item_id": "2",
            "title": "Fixture Adventure",
            "genres": ["Action"],
            "tags": ["Adventure"],
            "release_date": None,
            "metadata_missing": False,
            "training_interactions": 3,
            "recent_30d_interactions": 5,
        },
        {
            "item_id": "3",
            "title": "Fixture Puzzle",
            "genres": ["Puzzle"],
            "tags": ["Logic"],
            "release_date": None,
            "metadata_missing": False,
            "training_interactions": 2,
            "recent_30d_interactions": 9,
        },
    ]
    sp.save_npz(
        features_path, sp.csr_matrix(np.asarray([[1, 0], [0.9, 0.1], [0, 1]], dtype=np.float32))
    )
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    manifest = {
        "model_version": "synthetic-ci-fixture-v1",
        "selected_candidate": "synthetic-fixture",
        "split_manifest_sha256": "0" * 64,
        "features_file": features_path.name,
        "features_sha256": sha256(features_path),
        "catalog_file": catalog_path.name,
        "catalog_sha256": sha256(catalog_path),
        "content_rank_weight": 0.1,
    }
    (bundle / "release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    factor_path = als / "item_factors.npz"
    index_path = als / "item_ids.json"
    np.savez_compressed(
        factor_path, item_factors=np.asarray([[1, 0], [0.8, 0.2], [0, 1]], dtype=np.float32)
    )
    index_path.write_text(json.dumps(["1", "2", "3"]), encoding="utf-8")
    als_manifest = {
        "model": "synthetic_ci_fixture",
        "source_configuration": "synthetic-als-fixture",
        "split_manifest_sha256": "0" * 64,
        "factors": 2,
        "regularization": 0.01,
        "confidence": 11.0,
        "library_alpha_multiplier": 1.0,
        "item_factors_file": factor_path.name,
        "item_factors_sha256": sha256(factor_path),
        "item_ids_file": index_path.name,
        "item_ids_sha256": sha256(index_path),
    }
    (als / "manifest.json").write_text(json.dumps(als_manifest), encoding="utf-8")

    report = {
        "evaluation_split": "synthetic_ci_fixture",
        "split_manifest_sha256": "0" * 64,
        "candidate": {
            "name": "synthetic-fixture",
            "warm_catalog_ranking": {"mean_ndcg@10": 1.0},
            "catalog_coverage_at_10": 1.0,
            "tail_exposure_share_at_10": 0.5,
        },
        "recent_30d_popularity_baseline": {
            "warm_catalog_ranking": {"mean_ndcg@10": 1.0},
            "catalog_coverage_at_10": 1.0,
            "tail_exposure_share_at_10": 0.5,
        },
        "paired_ndcg_at_10_candidate_minus_recent30": {
            "mean_difference": 0.0,
            "ci_95_lower": 0.0,
            "ci_95_upper": 0.0,
        },
        "warm_catalog_users": 1,
        "future_target_users": 1,
    }
    (reports / "final_test.json").write_text(json.dumps(report), encoding="utf-8")
    print("Generated synthetic CI-only model, ALS, and evaluation fixtures.")


if __name__ == "__main__":
    main()
