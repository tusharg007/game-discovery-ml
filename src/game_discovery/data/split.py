from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date
from pathlib import Path
from typing import Any

import duckdb


def choose_global_cutoffs(
    daily_counts: list[tuple[date, int]],
    train_fraction: float = 0.70,
    validation_fraction: float = 0.15,
) -> tuple[date, date]:
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("Split fractions must be between zero and one")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("Train and validation fractions must leave a non-empty test window")
    ordered = sorted(daily_counts)
    total = sum(count for _, count in ordered)
    if total <= 0 or len(ordered) < 3:
        raise ValueError("Need positive events on at least three dates for a temporal split")
    thresholds = (
        math.ceil(total * train_fraction),
        math.ceil(total * (train_fraction + validation_fraction)),
    )
    cutoffs: list[date] = []
    cumulative = 0
    for event_date, count in ordered:
        cumulative += count
        while len(cutoffs) < len(thresholds) and cumulative >= thresholds[len(cutoffs)]:
            cutoffs.append(event_date)
    if len(cutoffs) != 2 or cutoffs[0] >= cutoffs[1]:
        raise ValueError("Whole-date split cannot produce three non-empty ordered windows")
    return cutoffs[0], cutoffs[1]


def _path_sql(path: Path) -> str:
    return "'" + path.resolve().as_posix().replace("'", "''") + "'"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)


def freeze_global_split(
    sample_path: Path,
    split_dir: Path,
    manifest_path: Path,
    *,
    train_fraction: float = 0.70,
    validation_fraction: float = 0.15,
) -> dict[str, Any]:
    sample_path = sample_path.resolve()
    split_dir.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        raise FileExistsError(
            f"A frozen split manifest already exists at {manifest_path}; create a new experiment to change it"
        )
    connection = duckdb.connect()
    source = _path_sql(sample_path)
    daily = connection.execute(
        f"SELECT event_date, count(*) FROM read_parquet({source}) GROUP BY event_date ORDER BY event_date"
    ).fetchall()
    cutoff_a, cutoff_b = choose_global_cutoffs(daily, train_fraction, validation_fraction)
    windows = {
        "train": f"event_date < DATE '{cutoff_a.isoformat()}'",
        "validation": (
            f"event_date >= DATE '{cutoff_a.isoformat()}' "
            f"AND event_date < DATE '{cutoff_b.isoformat()}'"
        ),
        "test": f"event_date >= DATE '{cutoff_b.isoformat()}'",
    }
    evidence: dict[str, Any] = {}
    split_hashes: dict[str, str] = {}
    for name, predicate in windows.items():
        destination = split_dir / f"{name}.parquet"
        temp = destination.with_name(f"{destination.name}.part")
        temp.unlink(missing_ok=True)
        output = _path_sql(temp)
        connection.execute(
            f"COPY (SELECT * FROM read_parquet({source}) WHERE {predicate}) "
            f"TO {output} (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        os.replace(temp, destination)
        output = _path_sql(destination)
        counts = connection.execute(
            f"""SELECT count(*), count(DISTINCT user_key), count(DISTINCT item_id),
                min(event_date), max(event_date)
                FROM read_parquet({output})"""
        ).fetchone()
        evidence[name] = {
            "events": counts[0],
            "users": counts[1],
            "items": counts[2],
            "first_date": counts[3],
            "last_date": counts[4],
            "parquet_sha256": _sha256(destination),
        }
        split_hashes[name] = evidence[name]["parquet_sha256"]
    connection.close()
    if not all(evidence[name]["events"] > 0 for name in windows):
        raise RuntimeError("Chronological split created an empty window")
    payload: dict[str, Any] = {
        "experiment": "future review-interaction ranking",
        "split_method": "global chronological; whole boundary dates remain on one side",
        "source_sample": str(sample_path),
        "source_sample_sha256": _sha256(sample_path),
        "source_event_count": sum(count for _, count in daily),
        "train_fraction_target": train_fraction,
        "validation_fraction_target": validation_fraction,
        "cutoff_a": cutoff_a.isoformat(),
        "cutoff_b": cutoff_b.isoformat(),
        "rules": {
            "train": "events strictly before cutoff_a",
            "validation": "cutoff_a through the day before cutoff_b",
            "test": "cutoff_b onward",
            "prediction_unit": "unordered set of new review interactions in each future window",
            "same_date_boundary": "all events on a boundary date stay in the same partition",
        },
        "partitions": evidence,
        "created_at": date.today().isoformat(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    payload["split_manifest_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    _atomic_json(manifest_path, payload)
    return payload
