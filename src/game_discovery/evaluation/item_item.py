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

from game_discovery.evaluation.als import KS, _pair_sets, _path_sql, _rank_scores
from game_discovery.evaluation.bootstrap import paired_user_bootstrap_difference
from game_discovery.evaluation.ranking import ranking_metrics, top_unseen_items


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate_item_item(
    split_dir: Path,
    split_manifest_path: Path,
    training_report_path: Path,
    popularity_report_path: Path,
    baseline_user_path: Path,
    report_path: Path,
    per_user_path: Path,
) -> dict[str, Any]:
    manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    train_path, validation_path = split_dir / "train.parquet", split_dir / "validation.parquet"
    if _sha256(train_path) != manifest["partitions"]["train"]["parquet_sha256"]:
        raise RuntimeError("Training split hash differs from the frozen manifest")
    if _sha256(validation_path) != manifest["partitions"]["validation"]["parquet_sha256"]:
        raise RuntimeError("Validation split hash differs from the frozen manifest")
    training = json.loads(training_report_path.read_text(encoding="utf-8"))
    popularity_report = json.loads(popularity_report_path.read_text(encoding="utf-8"))
    if training["split_manifest_sha256"] != manifest["split_manifest_sha256"]:
        raise RuntimeError("Item-item training evidence does not match the split manifest")
    if popularity_report["split_manifest_sha256"] != manifest["split_manifest_sha256"]:
        raise RuntimeError("Popularity baseline evidence does not match the split manifest")
    similarity_path = Path(training["similarity_path"])
    item_index_path = Path(training["item_index_path"])
    if _sha256(similarity_path) != training["similarity_sha256"]:
        raise RuntimeError("Item-item similarity artifact hash mismatch")
    if _sha256(item_index_path) != training["item_index_sha256"]:
        raise RuntimeError("Item-item index artifact hash mismatch")
    item_ids = np.asarray(json.loads(item_index_path.read_text(encoding="utf-8")), dtype=str)
    similarity = sp.load_npz(similarity_path).tocsr()
    matrix_kind = training.get("matrix_kind", "item_item_cosine")
    histories, targets = _pair_sets(train_path), _pair_sets(validation_path)
    connection = duckdb.connect()
    popularity_rows = connection.execute(
        f"SELECT item_id, count(*) FROM read_parquet({_path_sql(train_path)}) GROUP BY item_id"
    ).fetchall()
    connection.close()
    popularity = {str(item): int(count) for item, count in popularity_rows}
    catalog = sorted(popularity)
    expected_shape = (
        (len(catalog), similarity.shape[1])
        if matrix_kind == "content_tfidf"
        else (len(catalog), len(catalog))
    )
    if list(item_ids) != catalog or similarity.shape != expected_shape:
        raise RuntimeError("Item-item index differs from the frozen eligible catalog")
    item_index = {item: index for index, item in enumerate(item_ids)}
    popularity_ranking = sorted(catalog, key=lambda item: (-popularity[item], item))
    tail_items = set(popularity_ranking[math.ceil(len(catalog) * 0.20) :])
    warm_users = {
        user
        for user, relevant in targets.items()
        if histories.get(user) and relevant.intersection(catalog)
    }
    baseline_rows = pq.read_table(baseline_user_path).to_pylist()
    baseline = {
        row["user_key"]: float(row["warm_ndcg@10"])
        for row in baseline_rows
        if row["model"] == "global_popularity" and row["warm_ndcg@10"] is not None
    }
    if set(baseline) != warm_users:
        raise RuntimeError("Item-item and popularity warm-user cohorts differ")
    warm_metrics: list[dict[str, float]] = []
    rows: list[dict[str, Any]] = []
    all_recall = {k: 0.0 for k in KS}
    exposures = {k: Counter() for k in KS}
    exposure_total = {k: 0 for k in KS}
    unique_at_10: set[str] = set()
    for user in sorted(targets):
        seen = histories.get(user, set())
        if seen:
            seen_indices = [item_index[item] for item in seen if item in item_index]
            if matrix_kind == "content_tfidf":
                profile = similarity[seen_indices].sum(axis=0).T
                scores = np.asarray(similarity @ profile).ravel()
            else:
                scores = np.asarray(similarity[seen_indices].sum(axis=0)).ravel()
            ranked = _rank_scores(item_ids, scores, seen, 20, item_index)
            mode = training["model"]
        else:
            ranked = top_unseen_items(popularity_ranking, seen, 20)
            mode = "global_popularity_no_history_fallback"
        relevant = targets[user]
        reachable = relevant.intersection(catalog)
        warm = ranking_metrics(ranked, reachable, KS) if seen and reachable else None
        if warm:
            warm_metrics.append(warm)
        row: dict[str, Any] = {
            "user_key": user,
            "model": training["model"],
            "mode": mode,
            "has_history": bool(seen),
            "future_target_count": len(relevant),
            "reachable_target_count": len(reachable),
        }
        for k in KS:
            top = ranked[:k]
            row[f"all_target_recall@{k}"] = sum(item in relevant for item in top) / len(relevant)
            all_recall[k] += row[f"all_target_recall@{k}"]
            exposure_total[k] += len(top)
            exposures[k].update(top)
            if k == 10:
                unique_at_10.update(top)
            for metric in ("recall", "ndcg", "hit_rate"):
                row[f"warm_{metric}@{k}"] = warm[f"{metric}@{k}"] if warm else None
        rows.append(row)
    count_users, target_count = len(targets), sum(map(len, targets.values()))
    model_result = {
        "warm_catalog_users": len(warm_metrics),
        "warm_catalog_ranking": {
            f"mean_{metric}@{k}": (
                sum(row[f"{metric}@{k}"] for row in warm_metrics) / len(warm_metrics)
                if warm_metrics
                else None
            )
            for metric in ("recall", "ndcg", "hit_rate")
            for k in KS
        },
        "mean_all_target_recall_by_user": {f"recall@{k}": all_recall[k] / count_users for k in KS},
        "future_target_users": count_users,
        "future_target_count": target_count,
        "unreachable_future_target_count": sum(
            len(relevant.difference(catalog)) for relevant in targets.values()
        ),
        "users_with_no_reachable_future_target": sum(
            not relevant.intersection(catalog) for relevant in targets.values()
        ),
        "recommended_catalog_coverage_at_10": len(unique_at_10) / len(catalog),
        "mean_training_popularity_at_10": sum(
            popularity[item] * count for item, count in exposures[10].items()
        )
        / exposure_total[10],
        "tail_exposure_share_at_10": sum(
            count for item, count in exposures[10].items() if item in tail_items
        )
        / exposure_total[10],
        "exposure_hhi_at_10": sum(
            (count / exposure_total[10]) ** 2 for count in exposures[10].values()
        ),
        "paired_ndcg_at_10_vs_global_popularity": paired_user_bootstrap_difference(
            [baseline[user] for user in sorted(warm_users)],
            [float(row["warm_ndcg@10"]) for row in rows if row["warm_ndcg@10"] is not None],
            resamples=2_000,
            seed=1729,
        ),
    }
    per_user_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = per_user_path.with_name(f"{per_user_path.name}.part")
    pq.write_table(pa.Table.from_pylist(rows), temporary, compression="zstd")
    os.replace(temporary, per_user_path)
    report = {
        "experiment": "future review-interaction ranking",
        "evaluation_split": "validation",
        "split_manifest_sha256": manifest["split_manifest_sha256"],
        "fitting_cutoff": manifest["cutoff_a"],
        "eligible_catalog_count": len(catalog),
        "baseline_comparator": "global popularity from the same training cutoff",
        "model": model_result,
        "training": {k: v for k, v in training.items() if not k.endswith("_path")},
        "notes": (
            [
                "Static title, genre and tag features come from an untimestamped historical metadata snapshot.",
                "Each profile is the normalized-TF-IDF sum of the user's training items; candidates are ranked by cosine dot product.",
                "This separately labeled static-metadata experiment cannot establish what metadata was available historically.",
            ]
            if matrix_kind == "content_tfidf"
            else [
                "Binary co-occurrence cosine is shrunk by co-occurrence count and limited to 200 neighbors per item.",
                "All model information and popularity counts use training events strictly before cutoff A.",
            ]
        )
        + ["The final test partition has not been evaluated."],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_report = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary_report, report_path)
    return report
