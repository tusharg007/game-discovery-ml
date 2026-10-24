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
from threadpoolctl import threadpool_limits

from game_discovery.evaluation.bootstrap import paired_user_bootstrap_difference
from game_discovery.evaluation.ranking import ranking_metrics, top_unseen_items

KS = (5, 10, 20)


def _path_sql(path: Path) -> str:
    return "'" + path.resolve().as_posix().replace("'", "''") + "'"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rank_scores(
    item_ids: np.ndarray,
    scores: np.ndarray,
    seen: set[str],
    k: int,
    item_index: dict[str, int],
) -> list[str]:
    if scores.shape != (len(item_ids),) or not np.isfinite(scores).all():
        raise ValueError("ALS scores must be a finite vector aligned with the item index")
    candidates = np.arange(len(item_ids), dtype=np.int32)
    seen_indices = [item_index[item] for item in seen if item in item_index]
    if seen_indices:
        scores = scores.copy()
        scores[seen_indices] = -np.inf
        candidates = np.flatnonzero(np.isfinite(scores))
    if len(candidates) == 0:
        return []
    available_scores = scores[candidates]
    n = min(k, len(candidates))
    threshold = np.partition(available_scores, len(available_scores) - n)[len(available_scores) - n]
    higher = candidates[scores[candidates] > threshold]
    equal = candidates[scores[candidates] == threshold]
    higher_order = np.lexsort((item_ids[higher], -scores[higher]))
    selected = higher[higher_order].tolist()
    remaining = n - len(selected)
    if remaining:
        equal_order = np.argsort(item_ids[equal], kind="stable")
        selected.extend(equal[equal_order[:remaining]].tolist())
    return [str(item_ids[index]) for index in selected]


def _pair_sets(path: Path) -> dict[str, set[str]]:
    connection = duckdb.connect()
    cursor = connection.execute(
        f"SELECT user_key, item_id FROM read_parquet({_path_sql(path)}) ORDER BY user_key, item_id"
    )
    pairs: dict[str, set[str]] = {}
    while batch := cursor.fetchmany(100_000):
        for user, item in batch:
            pairs.setdefault(str(user), set()).add(str(item))
    connection.close()
    return pairs


def _metric_average(rows: list[dict[str, float]]) -> dict[str, float | None]:
    output: dict[str, float | None] = {}
    for metric in ("recall", "ndcg", "hit_rate"):
        for k in KS:
            key = f"{metric}@{k}"
            output[f"mean_{key}"] = sum(row[key] for row in rows) / len(rows) if rows else None
    return output


def evaluate_als_grid(
    split_dir: Path,
    split_manifest_path: Path,
    training_report_path: Path,
    popularity_report_path: Path,
    baseline_user_path: Path,
    report_path: Path,
    per_user_path: Path,
) -> dict[str, Any]:
    split_manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    train_path = split_dir / "train.parquet"
    validation_path = split_dir / "validation.parquet"
    if _sha256(train_path) != split_manifest["partitions"]["train"]["parquet_sha256"]:
        raise RuntimeError("Training split hash differs from the frozen manifest")
    if _sha256(validation_path) != split_manifest["partitions"]["validation"]["parquet_sha256"]:
        raise RuntimeError("Validation split hash differs from the frozen manifest")
    training = json.loads(training_report_path.read_text(encoding="utf-8"))
    popularity_report = json.loads(popularity_report_path.read_text(encoding="utf-8"))
    if training["training_split_sha256"] != split_manifest["partitions"]["train"]["parquet_sha256"]:
        raise RuntimeError("ALS training evidence does not match the frozen training split")
    if training["split_manifest_sha256"] != split_manifest["split_manifest_sha256"]:
        raise RuntimeError("ALS training evidence does not match the frozen split manifest")
    if popularity_report["split_manifest_sha256"] != split_manifest["split_manifest_sha256"]:
        raise RuntimeError("Popularity baseline evidence does not match the frozen split manifest")

    histories = _pair_sets(train_path)
    targets = _pair_sets(validation_path)
    connection = duckdb.connect()
    popularity_rows = connection.execute(
        f"SELECT item_id, count(*) FROM read_parquet({_path_sql(train_path)}) GROUP BY item_id"
    ).fetchall()
    connection.close()
    popularity = {str(item): int(count) for item, count in popularity_rows}
    catalog = sorted(popularity)
    popularity_ranking = sorted(catalog, key=lambda item: (-popularity[item], item))
    item_order = popularity_ranking
    tail_items = set(item_order[math.ceil(len(item_order) * 0.20) :])
    all_user_count = len(targets)
    total_target_count = sum(len(items) for items in targets.values())
    unreachable_targets = sum(len(items.difference(catalog)) for items in targets.values())
    no_reachable_users = sum(not items.intersection(catalog) for items in targets.values())
    warm_users = {
        user
        for user, relevant in targets.items()
        if histories.get(user) and relevant.intersection(catalog)
    }

    model_results: dict[str, Any] = {}
    all_rows: list[dict[str, Any]] = []
    baseline_rows = pq.read_table(baseline_user_path).to_pylist()
    baseline_contribution = {
        row["user_key"]: float(row["warm_ndcg@10"])
        for row in baseline_rows
        if row["model"] == "global_popularity" and row["warm_ndcg@10"] is not None
    }
    for config in training["configurations"]:
        model_name = config["name"]
        factors_path = Path(config["private_factors_path"])
        if _sha256(factors_path) != config["factors_sha256"]:
            raise RuntimeError(f"ALS factor artifact hash mismatch for {model_name}")
        with np.load(factors_path, allow_pickle=False) as arrays:
            user_factors = arrays["user_factors"]
            item_factors = arrays["item_factors"]
            user_keys = arrays["user_keys"].astype(str)
            item_ids = arrays["item_ids"].astype(str)
        if list(item_ids) != catalog:
            raise RuntimeError(
                f"ALS item index differs from the frozen eligible catalog: {model_name}"
            )
        if user_factors.shape[0] != len(user_keys) or item_factors.shape[0] != len(item_ids):
            raise RuntimeError(
                f"ALS factor dimensions do not match their saved indices: {model_name}"
            )
        user_index = {user: index for index, user in enumerate(user_keys)}
        catalog_index = {item: index for index, item in enumerate(item_ids)}
        warm_metrics: list[dict[str, float]] = []
        rows: list[dict[str, Any]] = []
        all_recall = {k: 0.0 for k in KS}
        exposures = {k: Counter() for k in KS}
        exposure_total = {k: 0 for k in KS}
        unique_at_10: set[str] = set()
        fallback_users = 0
        model_users = sorted(targets)
        rank_by_user: dict[str, list[str]] = {}
        score_users = [user for user in model_users if user in user_index and histories.get(user)]
        with threadpool_limits(limits=1, user_api="blas"):
            for start in range(0, len(score_users), 256):
                batch_users = score_users[start : start + 256]
                batch_indices = np.fromiter(
                    (user_index[user] for user in batch_users), dtype=np.int32
                )
                batch_scores = user_factors[batch_indices] @ item_factors.T
                for offset, user in enumerate(batch_users):
                    rank_by_user[user] = _rank_scores(
                        item_ids, batch_scores[offset], histories[user], 20, catalog_index
                    )
        for user in model_users:
            seen = histories.get(user, set())
            if user in rank_by_user:
                ranked = rank_by_user[user]
                mode = "als_user_factor"
            else:
                ranked = top_unseen_items(popularity_ranking, seen, 20)
                mode = "global_popularity_no_history_fallback"
                fallback_users += 1
            relevant_all = targets[user]
            reachable = relevant_all.intersection(catalog)
            warm = ranking_metrics(ranked, reachable, KS) if seen and reachable else None
            if warm:
                warm_metrics.append(warm)
            row: dict[str, Any] = {
                "user_key": user,
                "model": model_name,
                "mode": mode,
                "has_history": bool(seen),
                "future_target_count": len(relevant_all),
                "reachable_target_count": len(reachable),
            }
            for k in KS:
                top = ranked[:k]
                row[f"all_target_recall@{k}"] = sum(item in relevant_all for item in top) / len(
                    relevant_all
                )
                all_recall[k] += row[f"all_target_recall@{k}"]
                exposure_total[k] += len(top)
                exposures[k].update(top)
                if k == 10:
                    unique_at_10.update(top)
                for metric in ("recall", "ndcg", "hit_rate"):
                    row[f"warm_{metric}@{k}"] = warm[f"{metric}@{k}"] if warm else None
            rows.append(row)
        all_rows.extend(rows)
        model_results[model_name] = {
            "warm_catalog_users": len(warm_metrics),
            "warm_catalog_ranking": _metric_average(warm_metrics),
            "mean_all_target_recall_by_user": {
                f"recall@{k}": all_recall[k] / all_user_count if all_user_count else 0.0 for k in KS
            },
            "no_history_global_popularity_fallback_users": fallback_users,
            "future_target_users": all_user_count,
            "future_target_count": total_target_count,
            "unreachable_future_target_count": unreachable_targets,
            "users_with_no_reachable_future_target": no_reachable_users,
            "recommended_catalog_coverage_at_10": len(unique_at_10) / len(catalog)
            if catalog
            else 0.0,
            "mean_training_popularity_at_10": (
                sum(popularity[item] * count for item, count in exposures[10].items())
                / exposure_total[10]
                if exposure_total[10]
                else 0.0
            ),
            "tail_exposure_share_at_10": (
                sum(count for item, count in exposures[10].items() if item in tail_items)
                / exposure_total[10]
                if exposure_total[10]
                else 0.0
            ),
            "exposure_hhi_at_10": (
                sum((count / exposure_total[10]) ** 2 for count in exposures[10].values())
                if exposure_total[10]
                else 0.0
            ),
        }
        contribution = {
            row["user_key"]: float(row["warm_ndcg@10"])
            for row in rows
            if row["warm_ndcg@10"] is not None
        }
        users_for_ci = sorted(warm_users)
        if set(contribution) != warm_users or set(baseline_contribution) != warm_users:
            raise RuntimeError(f"Warm user cohorts differ across ALS and baseline: {model_name}")
        model_results[model_name]["paired_ndcg_at_10_vs_global_popularity"] = (
            paired_user_bootstrap_difference(
                [baseline_contribution[user] for user in users_for_ci],
                [contribution[user] for user in users_for_ci],
                resamples=2_000,
                seed=1729,
            )
        )

    per_user_path.parent.mkdir(parents=True, exist_ok=True)
    per_user_temp = per_user_path.with_name(f"{per_user_path.name}.part")
    pq.write_table(pa.Table.from_pylist(all_rows), per_user_temp, compression="zstd")
    os.replace(per_user_temp, per_user_path)
    report = {
        "experiment": "future review-interaction ranking",
        "evaluation_split": "validation",
        "split_manifest_sha256": split_manifest["split_manifest_sha256"],
        "fitting_cutoff": split_manifest["cutoff_a"],
        "eligible_catalog_count": len(catalog),
        "models": model_results,
        "baseline_comparator": "global popularity from the same training cutoff",
        "bootstrap": {
            "unit": "paired user",
            "metric": "warm-catalog NDCG@10",
            "resamples": 2_000,
            "seed": 1729,
        },
        "notes": [
            "ALS uses stored training user factors for users with prior interactions; no user factors are used for cold-start users.",
            "Users without training history fall back to global popularity, and the fallback count is reported.",
            "Each user's training items are excluded; score ties break by item_id.",
            "The final test partition has not been evaluated.",
        ],
        "models_detail": [
            {key: value for key, value in config.items() if key not in ("private_factors_path",)}
            for config in training["configurations"]
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    os.replace(temp, report_path)
    return report
