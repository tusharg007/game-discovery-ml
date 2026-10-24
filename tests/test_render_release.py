from __future__ import annotations

import hashlib
import json
import runpy
import zipfile
from pathlib import Path

import pytest

PREPARE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "deploy/render/prepare.py"))


def fixture_release(root: Path) -> None:
    for path in PREPARE["ASSETS"]:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic packaging fixture")
    champion_dir = root / "models/release/selected_candidate"
    als_dir = root / "models/release/alternates/als"
    champion = {
        "model_version": "synthetic-fixture",
        "split_manifest_sha256": "0" * 64,
        "catalog_sha256": hashlib.sha256((champion_dir / "catalog.json").read_bytes()).hexdigest(),
        "features_sha256": hashlib.sha256(
            (champion_dir / "content_features.npz").read_bytes()
        ).hexdigest(),
        "user_factors_exported": False,
        "user_identifiers_exported": False,
        "training_history_exported": False,
    }
    als = {
        "item_ids_sha256": hashlib.sha256((als_dir / "item_ids.json").read_bytes()).hexdigest(),
        "item_factors_sha256": hashlib.sha256(
            (als_dir / "item_factors.npz").read_bytes()
        ).hexdigest(),
        "user_factors_exported": False,
        "user_identifiers_exported": False,
        "training_histories_exported": False,
    }
    (champion_dir / "release_manifest.json").write_text(json.dumps(champion), encoding="utf-8")
    (als_dir / "manifest.json").write_text(json.dumps(als), encoding="utf-8")
    (root / "artifacts/reports/final_test.json").write_text(
        json.dumps({"split_manifest_sha256": "0" * 64}), encoding="utf-8"
    )


def test_render_staging_excludes_private_files_and_is_repeatable(tmp_path: Path):
    root = tmp_path / "checkout"
    fixture_release(root)
    private = root / "private/identity.json"
    private.parent.mkdir()
    private.write_text('{"synthetic_private":true}', encoding="utf-8")
    output = tmp_path / "output"
    first = PREPARE["stage_assets"](root, output)
    second = PREPARE["stage_assets"](root, output)
    assert first["archive_sha256"] == second["archive_sha256"]
    assert first["source_dataset_included"] is False
    assert first["user_level_data_included"] is False
    with zipfile.ZipFile(output / "render_release_assets.zip") as archive:
        assert set(archive.namelist()) == set(PREPARE["ASSETS"])
        assert not any(path.startswith("private/") for path in archive.namelist())


def test_render_staging_rejects_corrupt_or_user_bearing_bundle(tmp_path: Path):
    fixture_release(tmp_path)
    path = tmp_path / "models/release/selected_candidate/catalog.json"
    path.write_bytes(b"corrupted synthetic fixture")
    with pytest.raises(ValueError, match="hash mismatch"):
        PREPARE["verify_assets"](tmp_path)
    fixture_release(tmp_path)
    path = tmp_path / "models/release/selected_candidate/release_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["user_identifiers_exported"] = True
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="privacy flag"):
        PREPARE["verify_assets"](tmp_path)


def test_render_blueprint_enforces_free_plan_and_immutable_image():
    config = PREPARE["blueprint"]("ghcr.io/example/game-discovery@sha256:" + "a" * 64)
    assert list(config) == ["services"]
    service = config["services"][0]
    assert service["plan"] == "free"
    assert service["runtime"] == "image"
    assert service["numInstances"] == 1
    assert service["healthCheckPath"] == "/readyz"
    assert "disk" not in service and "scaling" not in service
    for image in ("ghcr.io/example/game-discovery:latest", "bad\nvalue", ""):
        with pytest.raises(ValueError):
            PREPARE["blueprint"](image)
