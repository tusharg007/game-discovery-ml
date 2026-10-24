from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import psutil
import pyarrow as pa
import pyarrow.parquet as pq

from game_discovery.evaluation.als import KS, _pair_sets, _path_sql
from game_discovery.evaluation.bootstrap import paired_user_bootstrap_difference
from game_discovery.evaluation.ranking import ranking_metrics, top_unseen_items
from game_discovery.serving.bundle import RecommendationBundle


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate_frozen_candidate_on_test(
    split_dir: Path,
    split_manifest_path: Path,
    selection_path: Path,
    bundle_dir: Path,
    report_path: Path,
    per_user_path: Path,
) -> dict[str, Any]:
    """Open the final test once for the already-frozen, refit bundle and its popularity comparator."""
    manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    bundle = RecommendationBundle(bundle_dir)
    if selection["split_manifest_sha256"] != manifest["split_manifest_sha256"]:
        raise RuntimeError("Frozen selection does not match the split manifest")
    if bundle.manifest["selection_record_sha256"] != _sha256(selection_path):
        raise RuntimeError("Release bundle was not exported from the frozen selection record")
    if bundle.manifest["split_manifest_sha256"] != manifest["split_manifest_sha256"]:
        raise RuntimeError("Release bundle does not match the frozen split manifest")
    if bundle.manifest["selected_candidate"] != selection["selected_candidate"]:
        raise RuntimeError("Release bundle candidate differs from the frozen selection")
    train_path = split_dir / "train.parquet"
    validation_path = split_dir / "validation.parquet"
    test_path = split_dir / "test.parquet"
    for name, path in (("train", train_path), ("validation", validation_path), ("test", test_path)):
        if _sha256(path) != manifest["partitions"][name]["parquet_sha256"]:
            raise RuntimeError(f"{name} split hash differs from the frozen manifest")
    started = time.perf_counter()
    history_connection = duckdb.connect()
    history_rows = history_connection.execute(
        f"SELECT user_key, item_id FROM read_parquet({_path_sql(train_path)}) "
        f"UNION ALL SELECT user_key, item_id FROM read_parquet({_path_sql(validation_path)}) "
        "ORDER BY user_key, item_id"
    ).fetchall()
    history_connection.close()
    histories: dict[str, set[str]] = {}
    for user, item in history_rows:
        histories.setdefault(str(user), set()).add(str(item))
    targets = _pair_sets(test_path)
    catalog = set(bundle.item_ids.tolist())
    recent_order = bundle.popularity_order
    popularity_ranking = [str(bundle.item_ids[index]) for index in recent_order]
    item_popularity = {
        item["item_id"]: int(item["training_interactions"]) for item in bundle.catalog
    }
    tail_order = sorted(item_popularity, key=lambda item: (-item_popularity[item], item))
    tail_items = set(tail_order[math.ceil(len(tail_order) * 0.20) :])
    warm_users = {
        user
        for user, relevant in targets.items()
        if histories.get(user) and relevant.intersection(catalog)
    }
    if not warm_users:
        raise RuntimeError("Final test has no warm-catalog users")
    rows: list[dict[str, Any]] = []
    warm_candidate: list[dict[str, float]] = []
    warm_baseline: list[dict[str, float]] = []
    candidate_contributions: dict[str, float] = {}
    baseline_contributions: dict[str, float] = {}
    model_exposure = {k: Counter() for k in KS}
    baseline_exposure = {k: Counter() for k in KS}
    candidate_covered: set[str] = set()
    baseline_covered: set[str] = set()
    candidate_all_recall = {k: 0.0 for k in KS}
    baseline_all_recall = {k: 0.0 for k in KS}
    model_total = {k: 0 for k in KS}
    baseline_total = {k: 0 for k in KS}
    for user in sorted(targets):
        seen = histories.get(user, set())
        recommendations = bundle.recommend_from_history(sorted(seen), k=20)["recommendations"]
        candidate_ranking = [str(item["item_id"]) for item in recommendations]
        baseline_ranking = top_unseen_items(popularity_ranking, seen, 20)
        relevant = targets[user]
        reachable = relevant.intersection(catalog)
        candidate_metrics = (
            ranking_metrics(candidate_ranking, reachable, KS) if seen and reachable else None
        )
        baseline_metrics = (
            ranking_metrics(baseline_ranking, reachable, KS) if seen and reachable else None
        )
        if user in warm_users:
            if candidate_metrics is None or baseline_metrics is None:
                raise RuntimeError("Candidate and baseline warm cohorts differ")
            warm_candidate.append(candidate_metrics)
            warm_baseline.append(baseline_metrics)
            candidate_contributions[user] = candidate_metrics["ndcg@10"]
            baseline_contributions[user] = baseline_metrics["ndcg@10"]
        row: dict[str, Any] = {
            "user_key": user,
            "model": "frozen_candidate",
            "has_history": bool(seen),
            "future_target_count": len(relevant),
            "reachable_target_count": len(reachable),
        }
        for k in KS:
            candidate_top = candidate_ranking[:k]
            baseline_top = baseline_ranking[:k]
            row[f"candidate_all_target_recall@{k}"] = sum(
                item in relevant for item in candidate_top
            ) / len(relevant)
            row[f"baseline_all_target_recall@{k}"] = sum(
                item in relevant for item in baseline_top
            ) / len(relevant)
            candidate_all_recall[k] += row[f"candidate_all_target_recall@{k}"]
            baseline_all_recall[k] += row[f"baseline_all_target_recall@{k}"]
            model_exposure[k].update(candidate_top)
            baseline_exposure[k].update(baseline_top)
            model_total[k] += len(candidate_top)
            baseline_total[k] += len(baseline_top)
            if k == 10:
                candidate_covered.update(candidate_top)
                baseline_covered.update(baseline_top)
            for metric in ("recall", "ndcg", "hit_rate"):
                row[f"candidate_warm_{metric}@{k}"] = (
                    candidate_metrics[f"{metric}@{k}"] if candidate_metrics else None
                )
                row[f"baseline_warm_{metric}@{k}"] = (
                    baseline_metrics[f"{metric}@{k}"] if baseline_metrics else None
                )
        rows.append(row)
    candidate_average = {
        f"mean_{metric}@{k}": sum(row[f"{metric}@{k}"] for row in warm_candidate)
        / len(warm_candidate)
        for metric in ("recall", "ndcg", "hit_rate")
        for k in KS
    }
    baseline_average = {
        f"mean_{metric}@{k}": sum(row[f"{metric}@{k}"] for row in warm_baseline)
        / len(warm_baseline)
        for metric in ("recall", "ndcg", "hit_rate")
        for k in KS
    }
    difference = paired_user_bootstrap_difference(
        [baseline_contributions[user] for user in sorted(warm_users)],
        [candidate_contributions[user] for user in sorted(warm_users)],
        resamples=2_000,
        seed=1729,
    )

    def exposure_summary(exposure: Counter, total: int, covered: set[str]) -> dict[str, float]:
        return {
            "catalog_coverage_at_10": len(covered) / len(catalog),
            "tail_exposure_share_at_10": sum(
                count for item, count in exposure.items() if item in tail_items
            )
            / total,
            "exposure_hhi_at_10": sum((count / total) ** 2 for count in exposure.values()),
            "mean_training_popularity_at_10": sum(
                item_popularity[item] * count for item, count in exposure.items()
            )
            / total,
        }

    report = {
        "experiment": "future review-interaction ranking",
        "evaluation_split": "test",
        "split_manifest_sha256": manifest["split_manifest_sha256"],
        "selection_record_sha256": _sha256(selection_path),
        "release_manifest_sha256": _sha256(bundle_dir / "release_manifest.json"),
        "prediction_window": {
            "start_inclusive": manifest["cutoff_b"],
            "end_inclusive": manifest["partitions"]["test"]["last_date"],
        },
        "eligible_catalog_count": len(catalog),
        "future_target_users": len(targets),
        "warm_catalog_users": len(warm_users),
        "unreachable_future_target_count": sum(
            len(items.difference(catalog)) for items in targets.values()
        ),
        "users_with_no_reachable_future_target": sum(
            not items.intersection(catalog) for items in targets.values()
        ),
        "users_without_training_history": sum(user not in histories for user in targets),
        "candidate": {
            "name": selection["selected_candidate"],
            "warm_catalog_ranking": candidate_average,
            "mean_all_target_recall_by_user": {
                f"recall@{k}": candidate_all_recall[k] / len(targets) for k in KS
            },
            **exposure_summary(model_exposure[10], model_total[10], candidate_covered),
        },
        "recent_30d_popularity_baseline": {
            "warm_catalog_ranking": baseline_average,
            "mean_all_target_recall_by_user": {
                f"recall@{k}": baseline_all_recall[k] / len(targets) for k in KS
            },
            **exposure_summary(baseline_exposure[10], baseline_total[10], baseline_covered),
        },
        "paired_ndcg_at_10_candidate_minus_recent30": difference,
        "runtime_seconds": time.perf_counter() - started,
        "process_peak_rss_mib": psutil.Process().memory_info().rss / (1024**2),
        "notes": [
            "The final test was evaluated after the selection record was frozen and the candidate was refit on train plus validation.",
            "Per-user history contains only events strictly before cutoff B; test outcomes do not update the model or history.",
            "Unreachable test targets count as misses in all-target Recall@K.",
            "The content component uses an untimestamped historical metadata snapshot.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_temp = report_path.with_suffix(report_path.suffix + ".tmp")
    report_temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(report_temp, report_path)
    per_user_path.parent.mkdir(parents=True, exist_ok=True)
    user_temp = per_user_path.with_name(f"{per_user_path.name}.part")
    pq.write_table(pa.Table.from_pylist(rows), user_temp, compression="zstd")
    os.replace(user_temp, per_user_path)
    return report
