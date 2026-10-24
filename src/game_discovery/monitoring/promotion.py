from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _artifact_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    if not path.is_dir():
        raise FileNotFoundError(path)
    for file_path in sorted(path.rglob("*")):
        if file_path.is_symlink():
            raise ValueError("model artifact trees may not contain symlinks")
        if file_path.is_file():
            digest.update(file_path.relative_to(path).as_posix().encode("utf-8"))
            with file_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def evaluate_promotion_gate(
    champion_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
    *,
    maximum_relative_ndcg_loss: float = 0.02,
) -> dict[str, Any]:
    champion_ndcg = float(champion_metrics["mean_ndcg@10"])
    candidate_ndcg = float(candidate_metrics["mean_ndcg@10"])
    if champion_ndcg <= 0 or candidate_ndcg < 0:
        raise ValueError("promotion NDCG metrics are invalid")
    relative_change = candidate_ndcg / champion_ndcg - 1.0
    accepted = relative_change >= -maximum_relative_ndcg_loss
    return {
        "accepted": accepted,
        "champion_mean_ndcg_at_10": champion_ndcg,
        "candidate_mean_ndcg_at_10": candidate_ndcg,
        "candidate_relative_change": relative_change,
        "maximum_relative_loss": maximum_relative_ndcg_loss,
        "reason": "within_ndcg_guardrail" if accepted else "regresses_beyond_ndcg_guardrail",
    }


class PromotionLedger:
    """Filesystem ledger for human-reviewed promotion and rollback decisions."""

    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "promotion_ledger.json"

    def _write(self, registry: dict[str, Any]) -> None:
        fd, temporary_name = tempfile.mkstemp(
            prefix=".promotion-", suffix=".tmp", dir=self.directory
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(registry, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def initialize(self, version: str, artifact_path: Path) -> dict[str, Any]:
        if self.path.exists():
            raise FileExistsError("promotion ledger is already initialized")
        relative_path, artifact_hash = self._validated_artifact(artifact_path)
        registry = {
            "active_version": version,
            "active_artifact_sha256": artifact_hash,
            "versions": {
                version: {"artifact_path": relative_path, "artifact_sha256": artifact_hash}
            },
            "history": [],
            "rejected_candidates": [],
            "event_stream": "synthetic_test",
        }
        self._write(registry)
        return registry

    def _validated_artifact(self, artifact_path: Path) -> tuple[str, str]:
        resolved = artifact_path.resolve()
        try:
            relative = resolved.relative_to(self.directory)
        except ValueError as exc:
            raise ValueError("promotion artifacts must be inside the ledger directory") from exc
        if relative.as_posix() == ".":
            raise ValueError("ledger directory is not an artifact")
        return relative.as_posix(), _artifact_hash(resolved)

    def read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def promote(
        self,
        version: str,
        artifact_path: Path,
        champion_metrics: dict[str, Any],
        candidate_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        if not version or Path(version).name != version:
            raise ValueError("model version must be a simple name")
        registry = self.read()
        relative_path, artifact_hash = self._validated_artifact(artifact_path)
        gate = evaluate_promotion_gate(champion_metrics, candidate_metrics)
        candidate = {
            "version": version,
            "artifact_path": relative_path,
            "artifact_sha256": artifact_hash,
            "gate": gate,
        }
        if not gate["accepted"]:
            registry["rejected_candidates"].append(candidate)
            self._write(registry)
            return {**candidate, "active_version": registry["active_version"]}
        previous = registry["active_version"]
        registry["history"].append(previous)
        registry["versions"][version] = {
            "artifact_path": relative_path,
            "artifact_sha256": artifact_hash,
        }
        registry["active_version"] = version
        registry["active_artifact_sha256"] = artifact_hash
        self._write(registry)
        return {**candidate, "active_version": version}

    def rollback(self, version: str) -> dict[str, Any]:
        registry = self.read()
        if version not in registry["versions"]:
            raise KeyError(f"unknown model version: {version}")
        entry = registry["versions"][version]
        path = (self.directory / entry["artifact_path"]).resolve()
        relative_path, artifact_hash = self._validated_artifact(path)
        if artifact_hash != entry["artifact_sha256"]:
            raise RuntimeError("rollback artifact hash does not match the ledger")
        registry["history"].append(registry["active_version"])
        registry["active_version"] = version
        registry["active_artifact_sha256"] = artifact_hash
        self._write(registry)
        return {
            "active_version": version,
            "artifact_path": relative_path,
            "artifact_sha256": artifact_hash,
        }
