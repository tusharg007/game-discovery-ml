from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import scipy.sparse as sp
from threadpoolctl import threadpool_limits


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_als_comparison_model(training_report_path: Path, output_dir: Path) -> dict[str, Any]:
    """Export item factors only for a clearly labeled validation-era ALS comparison."""
    report = json.loads(training_report_path.read_text(encoding="utf-8"))
    best = next(
        row for row in report["configurations"] if row["name"] == "als-f32-r0p01-a10.0-s1729"
    )
    factor_path = Path(best["private_factors_path"])
    if _sha256(factor_path) != best["factors_sha256"]:
        raise RuntimeError("ALS training factor hash mismatch")
    with np.load(factor_path, allow_pickle=False) as arrays:
        item_factors = arrays["item_factors"].astype(np.float32)
        item_ids = arrays["item_ids"].astype(str)
    if len(item_ids) != item_factors.shape[0]:
        raise RuntimeError("ALS item factor rows do not match their index")
    output_dir.mkdir(parents=True, exist_ok=True)
    factors_path = output_dir / "item_factors.npz"
    temp_path = output_dir / "item_factors.part.npz"
    np.savez_compressed(temp_path, item_factors=item_factors)
    os.replace(temp_path, factors_path)
    index_path = output_dir / "item_ids.json"
    index_path.write_text(
        json.dumps(item_ids.tolist(), separators=(",", ":")) + "\n", encoding="utf-8"
    )
    manifest = {
        "model": "implicit_als_comparison",
        "training_cutoff_exclusive": "2017-01-28",
        "training_split_sha256": report["training_split_sha256"],
        "split_manifest_sha256": report["split_manifest_sha256"],
        "source_configuration": best["name"],
        "factors": int(best["factors"]),
        "regularization": float(best["regularization"]),
        "confidence": float(best["stored_observed_confidence"]),
        "library_alpha_multiplier": float(best["library_alpha_multiplier"]),
        "item_count": len(item_ids),
        "item_factors_file": factors_path.name,
        "item_factors_sha256": _sha256(factors_path),
        "item_ids_file": index_path.name,
        "item_ids_sha256": _sha256(index_path),
        "user_factors_exported": False,
        "user_identifiers_exported": False,
        "training_histories_exported": False,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_temp = manifest_path.with_suffix(".json.tmp")
    manifest_temp.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(manifest_temp, manifest_path)
    return manifest


class ALSComparisonModel:
    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self.manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
        factors_path = model_dir / self.manifest["item_factors_file"]
        index_path = model_dir / self.manifest["item_ids_file"]
        if _sha256(factors_path) != self.manifest["item_factors_sha256"]:
            raise RuntimeError("ALS comparison item-factor hash mismatch")
        if _sha256(index_path) != self.manifest["item_ids_sha256"]:
            raise RuntimeError("ALS comparison item-index hash mismatch")
        with np.load(factors_path, allow_pickle=False) as arrays:
            self.item_factors = arrays["item_factors"].astype(np.float32)
        self.item_ids = np.asarray(json.loads(index_path.read_text(encoding="utf-8")), dtype=str)
        if self.item_factors.shape[0] != len(self.item_ids):
            raise RuntimeError("ALS comparison matrix and item index do not align")
        self.item_index = {item_id: index for index, item_id in enumerate(self.item_ids)}
        with threadpool_limits(limits=1, user_api="blas"):
            self.gram = self.item_factors.T @ self.item_factors
        self.regularization = float(self.manifest["regularization"])
        self.confidence = float(self.manifest["confidence"])

    def user_vector(self, seed_item_ids: list[str]) -> tuple[np.ndarray | None, int]:
        seed_indices = sorted(
            {self.item_index[item] for item in seed_item_ids if item in self.item_index}
        )
        unknown_count = len(set(seed_item_ids).difference(self.item_index))
        if not seed_indices:
            return None, unknown_count
        seed_factors = self.item_factors[seed_indices].astype(np.float64)
        confidence_delta = self.confidence - 1.0
        system = (
            self.gram.astype(np.float64)
            + np.eye(self.item_factors.shape[1], dtype=np.float64) * self.regularization
        )
        system += confidence_delta * (seed_factors.T @ seed_factors)
        target = self.confidence * seed_factors.sum(axis=0)
        try:
            vector = np.linalg.solve(system, target)
        except np.linalg.LinAlgError:
            vector = np.linalg.lstsq(system, target, rcond=None)[0]
        if not np.isfinite(vector).all():
            raise RuntimeError("ALS custom user-vector inference produced non-finite values")
        return vector.astype(np.float32), unknown_count

    def recommend(
        self,
        seed_item_ids: list[str],
        *,
        exclude_item_ids: list[str] | None = None,
        allowed_item_ids: set[str] | None = None,
        k: int = 10,
    ) -> dict[str, Any]:
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 20:
            raise ValueError("k must be an integer from 1 to 20")
        vector, unknown_count = self.user_vector(seed_item_ids)
        if vector is None:
            return {
                "model": "implicit_als_validation_reference",
                "recommendations": [],
                "fallback_reason": "no_seed_in_als_catalog",
                "unknown_seed_count": unknown_count,
            }
        with threadpool_limits(limits=1, user_api="blas"):
            scores = self.item_factors @ vector
        seen = set(seed_item_ids).union(exclude_item_ids or [])
        candidates = np.asarray(
            [
                index
                for index, item in enumerate(self.item_ids)
                if item not in seen and (allowed_item_ids is None or item in allowed_item_ids)
            ],
            dtype=np.int32,
        )
        order = candidates[np.lexsort((self.item_ids[candidates], -scores[candidates]))][:k]
        return {
            "model": "implicit_als_validation_reference",
            "recommendations": [
                {"item_id": str(self.item_ids[index]), "ranking_score": float(scores[index])}
                for index in order
            ],
            "fallback_reason": None
            if len(order)
            else "no_candidates_match_filter"
            if allowed_item_ids is not None
            else "all_candidates_excluded",
            "unknown_seed_count": unknown_count,
        }

    def verify_implicit_parity(self, seed_item_ids: list[str], k: int = 10) -> dict[str, Any]:
        from implicit.als import AlternatingLeastSquares

        seed_indices = sorted(
            {self.item_index[item] for item in seed_item_ids if item in self.item_index}
        )
        if not seed_indices:
            raise ValueError("Parity profile needs at least one item in the ALS catalog")
        user_indices = np.zeros(len(seed_indices), dtype=np.int32)
        confidence_values = np.full(len(seed_indices), self.confidence, dtype=np.float32)
        user_items = sp.csr_matrix(
            (confidence_values, (user_indices, seed_indices)),
            shape=(1, len(self.item_ids)),
        )
        model = AlternatingLeastSquares(
            factors=int(self.manifest["factors"]),
            regularization=self.regularization,
            alpha=self.manifest["library_alpha_multiplier"],
            iterations=1,
            num_threads=1,
            use_gpu=False,
        )
        model.item_factors = self.item_factors
        with threadpool_limits(limits=1, user_api="blas"):
            item_indices, library_scores = model.recommend(
                0,
                user_items,
                N=k,
                filter_already_liked_items=True,
                recalculate_user=True,
            )
        custom = self.recommend(seed_item_ids, k=k)["recommendations"]
        custom_ids = [row["item_id"] for row in custom]
        library_ids = [str(self.item_ids[int(index)]) for index in item_indices]
        return {
            "custom_item_ids": custom_ids,
            "library_item_ids": library_ids,
            "custom_scores": [row["ranking_score"] for row in custom],
            "library_scores": np.asarray(library_scores, dtype=float).tolist(),
            "ids_match": custom_ids == library_ids,
            "scores_allclose": bool(
                len(library_scores) == len(custom)
                and np.allclose(
                    np.asarray(library_scores),
                    np.asarray([row["ranking_score"] for row in custom]),
                    atol=1e-4,
                    rtol=1e-4,
                )
            ),
        }
