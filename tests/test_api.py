from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from fastapi.testclient import TestClient

from game_discovery.api import create_app


def _write_bundle(directory: Path) -> None:
    directory.mkdir(parents=True)
    features_path = directory / "features.npz"
    catalog_path = directory / "catalog.json"
    sp.save_npz(
        features_path, sp.csr_matrix(np.asarray([[1, 0], [0.9, 0.1], [0, 1]], dtype=np.float32))
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
        "selected_candidate": "fixture-candidate",
        "split_manifest_sha256": "fixture-split",
        "features_file": features_path.name,
        "features_sha256": hashlib.sha256(features_path.read_bytes()).hexdigest(),
        "catalog_file": catalog_path.name,
        "catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "content_rank_weight": 0.1,
    }
    (directory / "release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _client(tmp_path: Path) -> TestClient:
    bundle = tmp_path / "bundle"
    _write_bundle(bundle)
    return TestClient(create_app(bundle, als_model_dir=tmp_path / "no-als"))


def test_health_readiness_catalog_and_model_info(tmp_path: Path):
    client = _client(tmp_path)
    assert client.get("/healthz").json() == {"status": "healthy"}
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["model_version"] == "fixture-v1"
    assert client.get("/v1/catalog?q=action").json()["count"] == 2
    assert client.get("/v1/catalog?limit=1&sort=tail").json()["items"][0]["item_id"] == "1"
    info = client.get("/v1/model-info").json()
    assert info["feedback"]["enabled"] is False
    assert info["als_comparison_available"] is False


def test_recommendations_compare_models_and_report_unknown_seed_fallback(tmp_path: Path):
    client = _client(tmp_path)
    baseline = client.post("/v1/recommendations", json={"model": "recent_popularity", "k": 2})
    assert baseline.status_code == 200
    assert [item["item_id"] for item in baseline.json()["recommendations"]] == ["3", "2"]
    champion = client.post(
        "/v1/recommendations", json={"seed_item_ids": ["1", "not-a-game"], "k": 2}
    )
    assert champion.status_code == 200
    result = champion.json()
    assert result["fallback_reason"] == "unknown_seeds_used_known_content"
    assert result["unknown_seed_count"] == 1
    assert "1" not in {item["item_id"] for item in result["recommendations"]}
    assert all(
        "ranking_score" in item and "explanation_evidence" in item
        for item in result["recommendations"]
    )
    assert client.post("/v1/recommendations", json={"model": "als"}).status_code == 503


def test_request_limits_metrics_and_disabled_events_are_explicit(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/v1/recommendations", json={"k": 21}).status_code == 422
    assert client.post("/v1/recommendations", json={"seed_item_ids": ["1"] * 21}).status_code == 422
    event = client.post(
        "/v1/events",
        json={"event_type": "save", "item_id": "1", "impression_token": "unused"},
    )
    assert event.status_code == 503
    assert event.json()["persisted"] is False
    assert client.post("/v1/events", json={"free_text": "unbounded"}).status_code == 422
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "game_discovery_requests_total" in metrics.text


def test_unavailable_bundle_fails_readiness_and_serving(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "missing-bundle"))
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503
    assert client.get("/v1/catalog").status_code == 503
