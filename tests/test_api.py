from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import scipy.sparse as sp
from fastapi.testclient import TestClient

from game_discovery.api import create_app
from game_discovery.events.local import LocalEventStore


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
    assert client.post("/v1/events", json={"free_text": "unbounded"}).status_code == 503
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "game_discovery_requests_total" in metrics.text


def test_unavailable_bundle_fails_readiness_and_serving(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "missing-bundle"))
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503
    assert client.get("/v1/catalog").status_code == 503


def test_feedback_token_storage_dedup_and_process_restart(tmp_path: Path):
    bundle = tmp_path / "bundle"
    _write_bundle(bundle)
    event_dir = tmp_path / "events"
    secret = b"stable-local-test-secret-32-bytes!"
    first_client = TestClient(
        create_app(
            bundle,
            event_store=LocalEventStore(event_dir),
            event_signing_secret=secret,
            event_stream="synthetic_test",
        )
    )
    recommendation = first_client.post(
        "/v1/recommendations", json={"seed_item_ids": ["1"], "k": 2}
    ).json()
    assert recommendation["feedback_enabled"] is True
    first_item = recommendation["recommendations"][0]["item_id"]
    payload = {
        "event_id": str(uuid4()),
        "event_type": "save",
        "item_id": first_item,
        "impression_token": recommendation["impression_token"],
    }
    created = first_client.post("/v1/events", json=payload)
    assert created.status_code == 201
    assert created.json()["persisted"] is True

    restarted_client = TestClient(
        create_app(
            bundle,
            event_store=LocalEventStore(event_dir),
            event_signing_secret=secret,
            event_stream="synthetic_test",
        )
    )
    duplicate = restarted_client.post("/v1/events", json=payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    stored = LocalEventStore(event_dir).get(payload["event_id"])
    assert stored["event_stream"] == "synthetic_test"
    assert stored["model_version"] == "fixture-v1"
    assert stored["rank"] == 1
    assert "client_ip" not in stored
    assert (
        restarted_client.post("/v1/events", json={**payload, "free_text": "forbidden"}).status_code
        == 422
    )
    assert (
        restarted_client.post(
            "/v1/events", json={**payload, "item_id": "not-in-impression"}
        ).status_code
        == 422
    )


def test_feedback_process_rate_limit_is_bounded_and_per_session(tmp_path: Path):
    bundle = tmp_path / "bundle"
    _write_bundle(bundle)
    client = TestClient(
        create_app(
            bundle,
            event_store=LocalEventStore(tmp_path / "events"),
            event_signing_secret=b"stable-local-test-secret-32-bytes!",
            event_stream="synthetic_test",
        )
    )
    recommendation = client.post("/v1/recommendations", json={"seed_item_ids": ["1"]}).json()
    event = {
        "event_id": str(uuid4()),
        "event_type": "click",
        "item_id": recommendation["recommendations"][0]["item_id"],
        "impression_token": recommendation["impression_token"],
    }
    for _ in range(30):
        assert client.post("/v1/events", json=event).status_code in (200, 201)
    assert client.post("/v1/events", json={**event, "event_id": str(uuid4())}).status_code == 429


def test_feedback_storage_failure_is_reported_as_non_success(tmp_path: Path):
    class BrokenEventStore:
        def put_if_absent(self, event_id, record):
            raise OSError("simulated storage outage")

        def get(self, event_id):
            return None

    bundle = tmp_path / "bundle"
    _write_bundle(bundle)
    client = TestClient(
        create_app(
            bundle,
            event_store=BrokenEventStore(),
            event_signing_secret=b"stable-local-test-secret-32-bytes!",
            event_stream="synthetic_test",
        )
    )
    recommendation = client.post("/v1/recommendations", json={"seed_item_ids": ["1"]}).json()
    event = client.post(
        "/v1/events",
        json={
            "event_id": str(uuid4()),
            "event_type": "dismiss",
            "item_id": recommendation["recommendations"][0]["item_id"],
            "impression_token": recommendation["impression_token"],
        },
    )
    assert event.status_code == 503
    assert event.json()["detail"] == "Feedback storage failed"
