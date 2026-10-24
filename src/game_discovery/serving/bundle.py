from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import scipy.sparse as sp
from sklearn.feature_extraction.text import TfidfVectorizer


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sql_path(path: Path) -> str:
    return "'" + path.resolve().as_posix().replace("'", "''") + "'"


def export_selected_bundle(
    split_dir: Path,
    items_path: Path,
    selection_path: Path,
    split_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Refit the frozen static-content/popularity candidate before cutoff B and export items only."""
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    split_manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    if selection["split_manifest_sha256"] != split_manifest["split_manifest_sha256"]:
        raise RuntimeError("Selection record does not match the frozen split manifest")
    train_path = split_dir / "train.parquet"
    validation_path = split_dir / "validation.parquet"
    train_sql, validation_sql = _sql_path(train_path), _sql_path(validation_path)
    connection = duckdb.connect()
    fitting_rows = connection.execute(
        f"SELECT item_id, event_date FROM read_parquet({train_sql}) "
        f"UNION ALL SELECT item_id, event_date FROM read_parquet({validation_sql})"
    ).fetchall()
    metadata_rows = connection.execute(
        f"SELECT item_id, title, genres, tags, release_date, metadata_missing "
        f"FROM read_parquet({_sql_path(items_path)})"
    ).fetchall()
    connection.close()
    cutoff_b = split_manifest["cutoff_b"]
    from datetime import date, timedelta

    recent_start = date.fromisoformat(cutoff_b) - timedelta(days=30)
    all_counts: dict[str, int] = {}
    recent_counts: dict[str, int] = {}
    for item, event_date in fitting_rows:
        item_id = str(item)
        all_counts[item_id] = all_counts.get(item_id, 0) + 1
        if event_date >= recent_start:
            recent_counts[item_id] = recent_counts.get(item_id, 0) + 1
    item_ids = sorted(all_counts)
    metadata = {str(row[0]): row[1:] for row in metadata_rows}
    catalog: list[dict[str, Any]] = []
    documents: list[str] = []
    for item_id in item_ids:
        title, genres, tags, release_date, metadata_missing = metadata.get(
            item_id, (None, [], [], None, True)
        )
        genres, tags = list(genres or []), list(tags or [])
        fields = ([str(title)] if title else []) + genres + tags
        documents.append(" ".join(fields))
        catalog.append(
            {
                "item_id": item_id,
                "title": str(title) if title else f"Unknown game ({item_id})",
                "genres": genres,
                "tags": tags,
                "release_date": release_date.isoformat() if release_date else None,
                "metadata_missing": bool(metadata_missing),
                "training_interactions": all_counts[item_id],
                "recent_30d_interactions": recent_counts.get(item_id, 0),
            }
        )
    params = selection["parameters"]
    started = time.perf_counter()
    vectorizer = TfidfVectorizer(
        lowercase=True,
        strip_accents="unicode",
        token_pattern=r"(?u)\b\w+\b",
        ngram_range=tuple(params["tfidf_ngram_range"]),
        min_df=int(params["tfidf_min_df"]),
        max_features=int(params["tfidf_max_features"]),
        sublinear_tf=True,
        norm="l2",
        dtype=np.float32,
    )
    features = vectorizer.fit_transform(documents).tocsr()
    output_dir.mkdir(parents=True, exist_ok=True)
    features_path = output_dir / "content_features.npz"
    catalog_path = output_dir / "catalog.json"
    temporary_features = output_dir / "content_features.part.npz"
    sp.save_npz(temporary_features, features, compressed=True)
    temporary_features.replace(features_path)
    catalog_temp = catalog_path.with_suffix(".json.tmp")
    catalog_temp.write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    catalog_temp.replace(catalog_path)
    release_manifest = {
        "model_version": "portfolio-hybrid-content-popularity-v1",
        "selected_candidate": selection["selected_candidate"],
        "selection_record_sha256": _sha256(selection_path),
        "split_manifest_sha256": split_manifest["split_manifest_sha256"],
        "fit_cutoff_exclusive": cutoff_b,
        "training_event_count": len(fitting_rows),
        "catalog_item_count": len(catalog),
        "feature_count": int(features.shape[1]),
        "feature_nnz": int(features.nnz),
        "content_rank_weight": float(params["content_rank_weight"]),
        "recent_popularity_days": int(params["recent_popularity_days"]),
        "metadata_track": "static metadata snapshot; historical availability is unknown",
        "user_factors_exported": False,
        "user_identifiers_exported": False,
        "training_history_exported": False,
        "features_file": features_path.name,
        "features_sha256": _sha256(features_path),
        "catalog_file": catalog_path.name,
        "catalog_sha256": _sha256(catalog_path),
        "uncompressed_feature_bytes": int(
            features.data.nbytes + features.indices.nbytes + features.indptr.nbytes
        ),
        "bundle_file_bytes": features_path.stat().st_size + catalog_path.stat().st_size,
        "refit_runtime_seconds": time.perf_counter() - started,
    }
    manifest_path = output_dir / "release_manifest.json"
    manifest_temp = manifest_path.with_suffix(".json.tmp")
    manifest_temp.write_text(
        json.dumps(release_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(manifest_temp, manifest_path)
    return release_manifest


class RecommendationBundle:
    def __init__(self, bundle_dir: Path):
        self.bundle_dir = bundle_dir
        manifest_path = bundle_dir / "release_manifest.json"
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.features_path = bundle_dir / self.manifest["features_file"]
        self.catalog_path = bundle_dir / self.manifest["catalog_file"]
        if _sha256(self.features_path) != self.manifest["features_sha256"]:
            raise RuntimeError("Release content feature hash mismatch")
        if _sha256(self.catalog_path) != self.manifest["catalog_sha256"]:
            raise RuntimeError("Release catalog hash mismatch")
        self.features = sp.load_npz(self.features_path).tocsr()
        self.catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.item_ids = np.asarray([item["item_id"] for item in self.catalog], dtype=str)
        if self.features.shape[0] != len(self.catalog) or list(self.item_ids) != sorted(
            self.item_ids
        ):
            raise RuntimeError("Release content features and catalog index do not align")
        self.item_index = {item_id: index for index, item_id in enumerate(self.item_ids)}
        self.popularity_order = np.asarray(
            sorted(
                range(len(self.catalog)),
                key=lambda index: (
                    -int(self.catalog[index]["recent_30d_interactions"]),
                    self.catalog[index]["item_id"],
                ),
            ),
            dtype=np.int32,
        )

    def recommend(
        self,
        seed_item_ids: list[str],
        *,
        exclude_item_ids: list[str] | None = None,
        k: int = 10,
    ) -> dict[str, Any]:
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 20:
            raise ValueError("k must be an integer from 1 to 20")
        if len(seed_item_ids) > 20:
            raise ValueError("at most 20 seed games are allowed")
        seeds = list(dict.fromkeys(str(item) for item in seed_item_ids))
        return self._recommend_ids(
            seeds, exclude_item_ids or [], k, duplicate_seed_count=len(seed_item_ids) - len(seeds)
        )

    def recommend_from_history(self, history_item_ids: list[str], *, k: int = 10) -> dict[str, Any]:
        """Score an offline evaluation history without the visitor-facing 20-seed input cap."""
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 20:
            raise ValueError("k must be an integer from 1 to 20")
        history = list(dict.fromkeys(str(item) for item in history_item_ids))
        return self._recommend_ids(history, [], k)

    def _recommend_ids(
        self,
        seeds: list[str],
        exclude_item_ids: list[str],
        k: int,
        *,
        duplicate_seed_count: int = 0,
    ) -> dict[str, Any]:
        exclusions = {str(item) for item in (exclude_item_ids or [])}
        known_seed_indices = [self.item_index[item] for item in seeds if item in self.item_index]
        seen_ids = set(seeds).union(exclusions)
        candidates = np.asarray(
            [index for index, item_id in enumerate(self.item_ids) if item_id not in seen_ids],
            dtype=np.int32,
        )
        if not len(candidates):
            return {
                "model_version": self.manifest["model_version"],
                "model": "recent30_content_rank_fusion"
                if known_seed_indices
                else "recent30_popularity_fallback",
                "recommendations": [],
                "fallback_reason": "all_candidates_excluded",
                "unknown_seed_count": sum(item not in self.item_index for item in seeds),
            }
        if known_seed_indices:
            profile = self.features[known_seed_indices].sum(axis=0).T
            content_scores = np.asarray(self.features @ profile).ravel()
            content_order = candidates[
                np.lexsort((self.item_ids[candidates], -content_scores[candidates]))
            ]
            popularity_position = np.empty(len(self.item_ids), dtype=np.int32)
            popularity_position[self.popularity_order] = np.arange(
                len(self.popularity_order), dtype=np.int32
            )
            popularity_order = candidates[
                np.argsort(popularity_position[candidates], kind="stable")
            ]
            content_rank = np.zeros(len(self.item_ids), dtype=np.float32)
            popularity_rank = np.zeros(len(self.item_ids), dtype=np.float32)
            content_rank[content_order] = np.arange(len(candidates), 0, -1) / len(candidates)
            popularity_rank[popularity_order] = np.arange(len(candidates), 0, -1) / len(candidates)
            content_weight = float(self.manifest["content_rank_weight"])
            combined = (1.0 - content_weight) * popularity_rank + content_weight * content_rank
            order = candidates[np.lexsort((self.item_ids[candidates], -combined[candidates]))]
            model = "recent30_content_rank_fusion"
            fallback_reason = (
                "unknown_seeds_used_known_content" if len(known_seed_indices) < len(seeds) else None
            )
        else:
            order = candidates[
                np.lexsort(
                    (
                        self.item_ids[candidates],
                        -np.asarray(
                            [self.catalog[index]["recent_30d_interactions"] for index in candidates]
                        ),
                    )
                )
            ]
            model = "recent30_popularity_fallback"
            fallback_reason = "no_known_seed_games"
        selected = order[:k]
        recommendations: list[dict[str, Any]] = []
        seed_meta = [self.catalog[index] for index in known_seed_indices]
        for index in selected:
            item = self.catalog[int(index)]
            seed_genres = (
                set().union(*(set(seed["genres"]) for seed in seed_meta)) if seed_meta else set()
            )
            seed_tags = (
                set().union(*(set(seed["tags"]) for seed in seed_meta)) if seed_meta else set()
            )
            shared_genres = sorted(set(item["genres"]).intersection(seed_genres))
            shared_tags = sorted(set(item["tags"]).intersection(seed_tags))
            explanation = (
                f"Shares the {shared_genres[0]} genre with your selected games."
                if shared_genres
                else f"Shares the {shared_tags[0]} tag with your selected games."
                if shared_tags
                else "Ranked from your selected games' catalog features and recent review activity."
            )
            recommendations.append(
                {
                    "item_id": item["item_id"],
                    "title": item["title"],
                    "genres": item["genres"],
                    "tags": item["tags"],
                    "release_date": item["release_date"],
                    "explanation": explanation,
                }
            )
        return {
            "model_version": self.manifest["model_version"],
            "model": model,
            "recommendations": recommendations,
            "fallback_reason": fallback_reason,
            "unknown_seed_count": sum(item not in self.item_index for item in seeds),
            "duplicate_seed_count": duplicate_seed_count,
            "requested_k": k,
            "returned_count": len(recommendations),
        }
