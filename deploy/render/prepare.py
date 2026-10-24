"""Stage the exact item-only release locally; optionally generate an image-backed Blueprint.

This script never uploads assets or changes a Render account. Publication remains gated by
the unresolved permission recorded in DATA_CARD.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = (
    "models/release/selected_candidate/release_manifest.json",
    "models/release/selected_candidate/catalog.json",
    "models/release/selected_candidate/content_features.npz",
    "models/release/alternates/als/manifest.json",
    "models/release/alternates/als/item_ids.json",
    "models/release/alternates/als/item_factors.npz",
    "artifacts/reports/final_test.json",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_assets(root: Path) -> dict:
    for relative in ASSETS:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing or symlinked serving asset: {relative}")
    champion_dir = root / "models/release/selected_candidate"
    manifest = json.loads((champion_dir / "release_manifest.json").read_text(encoding="utf-8"))
    for field in (
        "user_factors_exported",
        "user_identifiers_exported",
        "training_history_exported",
    ):
        if manifest.get(field) is not False:
            raise ValueError(f"Champion privacy flag must be false: {field}")
    for name, key in (
        ("catalog.json", "catalog_sha256"),
        ("content_features.npz", "features_sha256"),
    ):
        if digest(champion_dir / name) != manifest[key]:
            raise ValueError(f"Champion hash mismatch: {name}")
    als_dir = root / "models/release/alternates/als"
    als = json.loads((als_dir / "manifest.json").read_text(encoding="utf-8"))
    for field in (
        "user_factors_exported",
        "user_identifiers_exported",
        "training_histories_exported",
    ):
        if als.get(field) is not False:
            raise ValueError(f"ALS privacy flag must be false: {field}")
    for name, key in (
        ("item_ids.json", "item_ids_sha256"),
        ("item_factors.npz", "item_factors_sha256"),
    ):
        if digest(als_dir / name) != als[key]:
            raise ValueError(f"ALS hash mismatch: {name}")
    report = json.loads((root / "artifacts/reports/final_test.json").read_text(encoding="utf-8"))
    if report["split_manifest_sha256"] != manifest["split_manifest_sha256"]:
        raise ValueError("Saved evaluation and model use different split manifests")
    return manifest


def blueprint(image_reference: str, region: str = "singapore") -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9./_-]+@sha256:[0-9a-f]{64}", image_reference):
        raise ValueError("Use a fully qualified registry image pinned by sha256 digest")
    if region not in {"singapore", "oregon", "ohio", "virginia", "frankfurt"}:
        raise ValueError("Unsupported Render region")
    return {
        "services": [
            {
                "type": "web",
                "name": "game-discovery-ml",
                "runtime": "image",
                "plan": "free",
                "region": region,
                "numInstances": 1,
                "image": {"url": image_reference},
                "healthCheckPath": "/readyz",
                "envVars": [
                    {"key": key, "value": value}
                    for key, value in (
                        ("PORT", "10000"),
                        ("OMP_NUM_THREADS", "1"),
                        ("OPENBLAS_NUM_THREADS", "1"),
                        ("MKL_NUM_THREADS", "1"),
                    )
                ],
            }
        ],
    }


def stage_assets(root: Path, output_dir: Path) -> dict:
    manifest = verify_assets(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / "render_release_assets.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(ASSETS):
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (root / relative).read_bytes())
    descriptor = {
        "provider": "render",
        "compute_plan": "free",
        "publication_gate": "unresolved; local staging only",
        "model_version": manifest["model_version"],
        "split_manifest_sha256": manifest["split_manifest_sha256"],
        "feedback_enabled": False,
        "archive_sha256": digest(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "files": [
            {
                "path": relative,
                "sha256": digest(root / relative),
                "bytes": (root / relative).stat().st_size,
            }
            for relative in ASSETS
        ],
    }
    (output_dir / "render_release_manifest.json").write_text(
        json.dumps(descriptor, indent=2) + "\n", encoding="utf-8"
    )
    return descriptor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/deployment")
    parser.add_argument("--image-reference")
    parser.add_argument("--region", default="singapore")
    args = parser.parse_args()
    descriptor = stage_assets(ROOT, args.output)
    if args.image_reference:
        # JSON is a subset of YAML; this produces a Blueprint without another dependency.
        (args.output / "render.yaml").write_text(
            json.dumps(blueprint(args.image_reference, args.region), indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(descriptor, indent=2))


if __name__ == "__main__":
    main()
