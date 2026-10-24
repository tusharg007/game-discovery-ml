from __future__ import annotations

import hashlib
import json
import math
import os
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from game_discovery.evaluation.bootstrap import paired_user_bootstrap_difference
from game_discovery.evaluation.ranking import ranking_metrics, top_unseen_items

KS = (5, 10, 20)
SEED = 1729


def _path_sql(path: Path) -> str:
    return "'" + path.resolve().as_posix().replace("'", "''") + "'"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_split_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    claimed = manifest.pop("split_manifest_sha256", None)
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    actual = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    manifest["split_manifest_sha256"] = claimed
    if claimed != actual:
        raise RuntimeError("Split manifest hash is invalid; refusing evaluation")
    return manifest


def _load_pairs(connection: duckdb.DuckDBPyConnection, path: Path) -> list[tuple[str, str]]:
    cursor = connection.execute(
        f"SELECT user_key, item_id FROM read_parquet({_path_sql(path)}) ORDER BY user_key, item_id"
    )
    result: list[tuple[str, str]] = []
    while batch := cursor.fetchmany(100_000):
        result.extend((str(user), str(item)) for user, item in batch)
    return result


def _metric_average(rows: list[dict[str, Any]], prefix: str) -> dict[str, float | None]:
    keys = [f"{metric}@{k}" for k in KS for metric in ("recall", "ndcg", "hit_rate")]
    count = len(rows)
    return {
        f"{prefix}_{key}": (sum(float(row[key]) for row in rows) / count if count else None)
        for key in keys
    }


def evaluate_validation_baselines(
    split_dir: Path,
    split_manifest_path: Path,
    report_path: Path,
    per_user_path: Path,
) -> dict[str, Any]:
    manifest = _verified_split_manifest(split_manifest_path)
    train_path = split_dir / "train.parquet"
    validation_path = split_dir / "validation.parquet"
    if _sha256(train_path) != manifest["partitions"]["train"]["parquet_sha256"]:
        raise RuntimeError("Training split hash differs from the frozen manifest")
    if _sha256(validation_path) != manifest["partitions"]["validation"]["parquet_sha256"]:
        raise RuntimeError("Validation split hash differs from the frozen manifest")

    cutoff = date.fromisoformat(manifest["cutoff_a"])
    connection = duckdb.connect()
    train_sql = _path_sql(train_path)
    train_count_rows = connection.execute(
        f"SELECT item_id, count(*) AS n FROM read_parquet({train_sql}) GROUP BY item_id"
    ).fetchall()
    popularity = {str(item): int(count) for item, count in train_count_rows}
    catalog = sorted(popularity)
    if not catalog:
        raise RuntimeError("Training window has an empty eligible catalog")

    histories: dict[str, set[str]] = {}
    for user, item in _load_pairs(connection, train_path):
        histories.setdefault(user, set()).add(item)
    targets: dict[str, set[str]] = {}
    for user, item in _load_pairs(connection, validation_path):
        targets.setdefault(user, set()).add(item)
    connection.close()

    recent_rankings: dict[str, list[str]] = {}
    for days in (30, 90):
        start = cutoff - timedelta(days=days)
        recent_connection = duckdb.connect()
        recent = recent_connection.execute(
            f"""SELECT item_id, count(*) AS n FROM read_parquet({train_sql})
                WHERE event_date >= DATE '{start.isoformat()}'
                GROUP BY item_id"""
        ).fetchall()
        recent_connection.close()
        counts = {str(item): int(count) for item, count in recent}
        recent_rankings[f"recent_popularity_{days}d"] = sorted(
            catalog, key=lambda item: (-counts.get(item, 0), item)
        )

    rankings = {
        "uniform_random": catalog.copy(),
        "global_popularity": sorted(catalog, key=lambda item: (-popularity[item], item)),
        **recent_rankings,
    }
    random.Random(SEED).shuffle(rankings["uniform_random"])
    item_order = sorted(catalog, key=lambda item: (-popularity[item], item))
    tail_items = set(item_order[math.ceil(len(item_order) * 0.20) :])

    per_user_rows: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    all_future_users = len(targets)
    total_targets = sum(len(items) for items in targets.values())
    users_with_history = sum(user in histories for user in targets)
    users_with_reachable_target = sum(
        bool(items.intersection(catalog)) for items in targets.values()
    )
    users_with_no_reachable_target = sum(
        not items.intersection(catalog) for items in targets.values()
    )
    unreachable_targets = sum(len(items.difference(catalog)) for items in targets.values())
    warm_count = sum(
        bool(histories.get(user)) and bool(items.intersection(catalog))
        for user, items in targets.items()
    )

    for model_name, item_ranking in rankings.items():
        warm_metrics: list[dict[str, float]] = []
        all_recall_sums = {k: 0.0 for k in KS}
        exposures = {k: Counter() for k in KS}
        exposure_total = {k: 0 for k in KS}
        recommended_items = {k: set() for k in KS}
        user_count = 0
        for user in sorted(targets):
            relevant_all = targets[user]
            reachable = relevant_all.intersection(catalog)
            history = histories.get(user, set())
            recommendations = top_unseen_items(item_ranking, history, 20)
            user_count += 1
            if reachable and history:
                warm = ranking_metrics(recommendations, reachable, KS)
                warm_metrics.append(warm)
            else:
                warm = None
            for k in KS:
                top = recommendations[:k]
                all_recall_sums[k] += sum(item in relevant_all for item in top) / len(relevant_all)
                exposure_total[k] += len(top)
                exposures[k].update(top)
                recommended_items[k].update(top)
            row: dict[str, Any] = {
                "user_key": user,
                "model": model_name,
                "has_history": bool(history),
                "future_target_count": len(relevant_all),
                "reachable_target_count": len(reachable),
            }
            for k in KS:
                row[f"all_target_recall@{k}"] = sum(
                    item in relevant_all for item in recommendations[:k]
                ) / len(relevant_all)
                for metric in ("recall", "ndcg", "hit_rate"):
                    row[f"warm_{metric}@{k}"] = warm[f"{metric}@{k}"] if warm else None
            per_user_rows.append(row)

        summary: dict[str, Any] = {
            "future_target_users": all_future_users,
            "users_with_history": users_with_history,
            "users_with_reachable_future_target": users_with_reachable_target,
            "users_with_no_reachable_future_target": users_with_no_reachable_target,
            "warm_catalog_users": warm_count,
            "future_target_count": total_targets,
            "unreachable_future_target_count": unreachable_targets,
            "mean_all_target_recall_by_user": {
                f"recall@{k}": all_recall_sums[k] / user_count if user_count else 0.0 for k in KS
            },
            "warm_catalog_ranking": _metric_average(warm_metrics, "mean"),
            "recommended_catalog_coverage_at_10": (
                len(recommended_items[10]) / len(catalog) if catalog else 0.0
            ),
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
        summaries[model_name] = summary

    per_user_path.parent.mkdir(parents=True, exist_ok=True)
    per_user_temp = per_user_path.with_name(f"{per_user_path.name}.part")
    table = pa.Table.from_pylist(per_user_rows)
    pq.write_table(table, per_user_temp, compression="zstd")
    os.replace(per_user_temp, per_user_path)
    warm_by_model = {
        name: {
            row["user_key"]: float(row["warm_ndcg@10"])
            for row in per_user_rows
            if row["model"] == name and row["warm_ndcg@10"] is not None
        }
        for name in rankings
    }
    warm_users = sorted(warm_by_model["global_popularity"])
    bootstrap_results = {
        name: paired_user_bootstrap_difference(
            [warm_by_model["global_popularity"][user] for user in warm_users],
            [warm_by_model[name][user] for user in warm_users],
            resamples=2_000,
            seed=SEED,
        )
        for name in rankings
    }
    report = {
        "experiment": "future review-interaction ranking",
        "evaluation_split": "validation",
        "split_manifest_sha256": manifest["split_manifest_sha256"],
        "fitting_cutoff": manifest["cutoff_a"],
        "prediction_window": {
            "start": manifest["cutoff_a"],
            "end_exclusive": manifest["cutoff_b"],
        },
        "eligible_catalog_count": len(catalog),
        "eligible_catalog_rule": "all items observed before cutoff A; each user's training items excluded",
        "recommendation_count_for_exposure_metrics": 10,
        "tail_definition": "bottom 80 percent of training-catalog items by count; popularity ties break by item_id",
        "random_seed": SEED,
        "users_with_future_targets": all_future_users,
        "users_without_training_history": all_future_users - users_with_history,
        "users_with_no_reachable_future_target": users_with_no_reachable_target,
        "unreachable_future_target_count": unreachable_targets,
        "models": summaries,
        "paired_user_bootstrap_vs_global_popularity_ndcg_at_10": bootstrap_results,
        "notes": [
            "Popularity counts use only events strictly before cutoff A.",
            "All models use the same future-target users, eligible catalog, and per-user exclusions.",
            "All-target recall divides each user's hits by every future target, so unreachable targets count as misses.",
            "Warm-catalog NDCG/Recall/HitRate include only users with prior history and at least one reachable future target.",
            "These are held-out review interactions, not verified likes or causal engagement outcomes.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_temp = report_path.with_name(f"{report_path.name}.tmp")
    report_temp.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    os.replace(report_temp, report_path)
    return report
