from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import scipy.sparse as sp

from game_discovery.evaluation.als import KS, _pair_sets, _path_sql
from game_discovery.evaluation.bootstrap import paired_user_bootstrap_difference
from game_discovery.evaluation.ranking import ranking_metrics, top_unseen_items

BLEND_WEIGHT = 0.25


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rank_fusion(
    item_ids: np.ndarray,
    candidate_indices: np.ndarray,
    popularity_order: np.ndarray,
    model_scores: np.ndarray,
    weight: float,
    k: int,
) -> list[str]:
    popularity_position = np.empty(len(item_ids), dtype=np.int32)
    popularity_position[popularity_order] = np.arange(len(popularity_order), dtype=np.int32)
    pop_order = candidate_indices[np.argsort(popularity_position[candidate_indices], kind="stable")]
    pop_scores = np.zeros(len(item_ids), dtype=np.float32)
    pop_scores[pop_order] = np.arange(len(pop_order), 0, -1, dtype=np.float32) / len(pop_order)
    model_order = candidate_indices[
        np.lexsort((item_ids[candidate_indices], -model_scores[candidate_indices]))
    ]
    model_scores_rank = np.zeros(len(item_ids), dtype=np.float32)
    model_scores_rank[model_order] = np.arange(len(model_order), 0, -1, dtype=np.float32) / len(
        model_order
    )
    combined = (1.0 - weight) * pop_scores + weight * model_scores_rank
    order = candidate_indices[
        np.lexsort((item_ids[candidate_indices], -combined[candidate_indices]))
    ]
    return [str(item_ids[index]) for index in order[:k]]


def evaluate_validation_hybrids(
    split_dir: Path,
    split_manifest_path: Path,
    als_training_path: Path,
    item_item_training_path: Path,
    content_training_path: Path,
    baseline_report_path: Path,
    baseline_user_path: Path,
    report_path: Path,
    per_user_path: Path,
) -> dict[str, Any]:
    manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    baseline_report = json.loads(baseline_report_path.read_text(encoding="utf-8"))
    if baseline_report["split_manifest_sha256"] != manifest["split_manifest_sha256"]:
        raise RuntimeError("Popularity baseline evidence does not match the frozen split")
    train_path, validation_path = split_dir / "train.parquet", split_dir / "validation.parquet"
    if _sha256(train_path) != manifest["partitions"]["train"]["parquet_sha256"]:
        raise RuntimeError("Training split hash differs from the frozen manifest")
    if _sha256(validation_path) != manifest["partitions"]["validation"]["parquet_sha256"]:
        raise RuntimeError("Validation split hash differs from the frozen manifest")
    histories, targets = _pair_sets(train_path), _pair_sets(validation_path)
    connection = duckdb.connect()
    popularity_rows = connection.execute(
        f"SELECT item_id, count(*) FROM read_parquet({_path_sql(train_path)}) GROUP BY item_id"
    ).fetchall()
    cutoff = manifest["cutoff_a"]
    recent_rows = connection.execute(
        f"SELECT item_id, count(*) FROM read_parquet({_path_sql(train_path)}) "
        f"WHERE event_date >= DATE '{(np.datetime64(cutoff) - np.timedelta64(30, 'D'))}' "
        "GROUP BY item_id"
    ).fetchall()
    connection.close()
    global_counts = {str(item): int(count) for item, count in popularity_rows}
    recent_counts = {str(item): int(count) for item, count in recent_rows}
    catalog = sorted(global_counts)
    item_ids = np.asarray(catalog, dtype=str)
    item_index = {item: index for index, item in enumerate(catalog)}
    popularity_order = np.asarray(
        [
            item_index[item]
            for item in sorted(catalog, key=lambda item: (-recent_counts.get(item, 0), item))
        ],
        dtype=np.int32,
    )
    recent_ranking = [catalog[index] for index in popularity_order]
    tail = set(
        sorted(catalog, key=lambda item: (-global_counts[item], item))[
            math.ceil(len(catalog) * 0.2) :
        ]
    )
    baseline_rows = pq.read_table(baseline_user_path).to_pylist()
    recent_baseline = {
        row["user_key"]: float(row["warm_ndcg@10"])
        for row in baseline_rows
        if row["model"] == "recent_popularity_30d" and row["warm_ndcg@10"] is not None
    }
    warm_users = {
        user
        for user, relevant in targets.items()
        if histories.get(user) and relevant.intersection(catalog)
    }
    if set(recent_baseline) != warm_users:
        raise RuntimeError("Hybrid and recent-popularity warm cohorts differ")

    item_train = json.loads(item_item_training_path.read_text(encoding="utf-8"))
    content_train = json.loads(content_training_path.read_text(encoding="utf-8"))
    item_sim_path = Path(item_train["similarity_path"])
    content_matrix_path = Path(content_train["similarity_path"])
    item_ids_path = Path(item_train["item_index_path"])
    content_ids_path = Path(content_train["item_index_path"])
    for path, evidence, key in (
        (item_sim_path, item_train, "similarity_sha256"),
        (content_matrix_path, content_train, "similarity_sha256"),
        (item_ids_path, item_train, "item_index_sha256"),
        (content_ids_path, content_train, "item_index_sha256"),
    ):
        if _sha256(path) != evidence[key]:
            raise RuntimeError(f"Hybrid source artifact hash mismatch: {path}")
    if (
        item_train["split_manifest_sha256"] != manifest["split_manifest_sha256"]
        or content_train["split_manifest_sha256"] != manifest["split_manifest_sha256"]
    ):
        raise RuntimeError("Hybrid training artifacts do not match the frozen split")
    if (
        json.loads(item_ids_path.read_text(encoding="utf-8")) != catalog
        or json.loads(content_ids_path.read_text(encoding="utf-8")) != catalog
    ):
        raise RuntimeError("Hybrid item indices differ from the eligible training catalog")
    item_similarity = sp.load_npz(item_sim_path).tocsr()
    content_features = sp.load_npz(content_matrix_path).tocsr()
    als_report = json.loads(als_training_path.read_text(encoding="utf-8"))
    als_config = next(
        row for row in als_report["configurations"] if row["name"] == "als-f32-r0p01-a10.0-s1729"
    )
    if als_report["split_manifest_sha256"] != manifest["split_manifest_sha256"]:
        raise RuntimeError("ALS training artifacts do not match the frozen split")
    factor_path = Path(als_config["private_factors_path"])
    if _sha256(factor_path) != als_config["factors_sha256"]:
        raise RuntimeError("Hybrid ALS factor artifact hash mismatch")
    with np.load(factor_path, allow_pickle=False) as factors:
        user_factors = factors["user_factors"]
        user_keys = factors["user_keys"].astype(str)
        factor_item_ids = factors["item_ids"].astype(str)
        item_factors = factors["item_factors"]
    if list(factor_item_ids) != catalog:
        raise RuntimeError("Hybrid ALS item index differs from the eligible catalog")
    factor_user_index = {user: index for index, user in enumerate(user_keys)}

    blend_configs = [
        ("item_item", "hybrid_recent30_item_item_w25", BLEND_WEIGHT),
        ("content", "hybrid_recent30_content_w25", BLEND_WEIGHT),
        ("content", "hybrid_recent30_content_w10", 0.10),
        ("content", "hybrid_recent30_content_w15", 0.15),
        ("content", "hybrid_recent30_content_w20", 0.20),
        ("als", "hybrid_recent30_als_w25", BLEND_WEIGHT),
    ]
    aggregate: dict[str, Any] = {}
    per_user_rows: list[dict[str, Any]] = []
    for model_kind, model_name, blend_weight in blend_configs:
        warm_metrics: list[dict[str, float]] = []
        contributions: dict[str, float] = {}
        all_recall = {k: 0.0 for k in KS}
        exposures = {k: Counter() for k in KS}
        exposure_total = {k: 0 for k in KS}
        unique_at_10: set[str] = set()
        for user in sorted(targets):
            seen = histories.get(user, set())
            seen_indices = np.asarray(
                [item_index[item] for item in seen if item in item_index], dtype=np.int32
            )
            candidates = np.ones(len(catalog), dtype=np.bool_)
            candidates[seen_indices] = False
            candidate_indices = np.flatnonzero(candidates)
            if not len(seen_indices):
                ranked = top_unseen_items(recent_ranking, seen, 20)
                mode = "recent_popularity_no_history_fallback"
            else:
                if model_kind == "item_item":
                    model_scores = np.asarray(item_similarity[seen_indices].sum(axis=0)).ravel()
                elif model_kind == "content":
                    profile = content_features[seen_indices].sum(axis=0).T
                    model_scores = np.asarray(content_features @ profile).ravel()
                else:
                    factor_index = factor_user_index.get(user)
                    if factor_index is None:
                        ranked = top_unseen_items(recent_ranking, seen, 20)
                        mode = "recent_popularity_unseen_user_fallback"
                        model_scores = None
                    else:
                        model_scores = user_factors[factor_index] @ item_factors.T
                if model_scores is not None:
                    ranked = _rank_fusion(
                        item_ids,
                        candidate_indices,
                        popularity_order,
                        model_scores,
                        blend_weight,
                        20,
                    )
                    mode = f"{model_name}_rank_fusion"
            relevant = targets[user]
            reachable = relevant.intersection(catalog)
            warm = ranking_metrics(ranked, reachable, KS) if seen and reachable else None
            if warm:
                warm_metrics.append(warm)
                contributions[user] = warm["ndcg@10"]
            row: dict[str, Any] = {
                "user_key": user,
                "model": model_name,
                "mode": mode,
                "future_target_count": len(relevant),
                "reachable_target_count": len(reachable),
            }
            for k in KS:
                top = ranked[:k]
                row[f"all_target_recall@{k}"] = sum(item in relevant for item in top) / len(
                    relevant
                )
                all_recall[k] += row[f"all_target_recall@{k}"]
                exposure_total[k] += len(top)
                exposures[k].update(top)
                if k == 10:
                    unique_at_10.update(top)
                for metric in ("recall", "ndcg", "hit_rate"):
                    row[f"warm_{metric}@{k}"] = warm[f"{metric}@{k}"] if warm else None
            per_user_rows.append(row)
        bootstrap = paired_user_bootstrap_difference(
            [recent_baseline[user] for user in sorted(warm_users)],
            [contributions[user] for user in sorted(warm_users)],
            resamples=2_000,
            seed=1729,
        )
        aggregate[model_name] = {
            "warm_catalog_users": len(warm_metrics),
            "warm_catalog_ranking": {
                f"mean_{metric}@{k}": sum(row[f"{metric}@{k}"] for row in warm_metrics)
                / len(warm_metrics)
                for metric in ("recall", "ndcg", "hit_rate")
                for k in KS
            },
            "mean_all_target_recall_by_user": {
                f"recall@{k}": all_recall[k] / len(targets) for k in KS
            },
            "recommended_catalog_coverage_at_10": len(unique_at_10) / len(catalog),
            "mean_training_popularity_at_10": sum(
                global_counts[item] * count for item, count in exposures[10].items()
            )
            / exposure_total[10],
            "tail_exposure_share_at_10": sum(
                count for item, count in exposures[10].items() if item in tail
            )
            / exposure_total[10],
            "exposure_hhi_at_10": sum(
                (count / exposure_total[10]) ** 2 for count in exposures[10].values()
            ),
            "blend_weight_for_model_rank": blend_weight,
            "baseline": "recent_popularity_30d",
            "paired_ndcg_at_10_vs_recent_popularity_30d": bootstrap,
        }
    report = {
        "experiment": "future review-interaction ranking",
        "evaluation_split": "validation",
        "split_manifest_sha256": manifest["split_manifest_sha256"],
        "fitting_cutoff": cutoff,
        "eligible_catalog_count": len(catalog),
        "models": aggregate,
        "notes": [
            "Blends combine normalized within-catalog rank percentiles with recent-30-day popularity.",
            "The fixed model-rank weight is 0.25; rank fusion avoids mixing raw, incomparable score scales.",
            "Content uses an untimestamped historical metadata snapshot and is reported as a static-metadata experiment.",
            "The final test partition has not been evaluated.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, report_path)
    per_user_path.parent.mkdir(parents=True, exist_ok=True)
    user_temp = per_user_path.with_name(f"{per_user_path.name}.part")
    pq.write_table(pa.Table.from_pylist(per_user_rows), user_temp, compression="zstd")
    os.replace(user_temp, per_user_path)
    return report
