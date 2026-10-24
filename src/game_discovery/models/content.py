from __future__ import annotations

import hashlib
import json
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


def train_static_metadata_tfidf(
    train_path: Path,
    items_path: Path,
    split_manifest_path: Path,
    feature_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    """Build sparse title/genre/tag TF-IDF features for the pre-cutoff item catalog."""
    manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    train_hash = _sha256(train_path)
    if train_hash != manifest["partitions"]["train"]["parquet_sha256"]:
        raise RuntimeError("Training input does not match the frozen split manifest")
    train_sql = "'" + train_path.resolve().as_posix().replace("'", "''") + "'"
    item_sql = "'" + items_path.resolve().as_posix().replace("'", "''") + "'"
    connection = duckdb.connect()
    rows = connection.execute(
        "SELECT DISTINCT item_id FROM read_parquet(" + train_sql + ") ORDER BY item_id"
    ).fetchall()
    item_rows = connection.execute(
        "SELECT item_id, title, genres, tags FROM read_parquet(" + item_sql + ")"
    ).fetchall()
    event_count, user_count = connection.execute(
        f"SELECT count(*), count(DISTINCT user_key) FROM read_parquet({train_sql})"
    ).fetchone()
    connection.close()
    item_ids = [str(row[0]) for row in rows]
    metadata = {str(row[0]): row[1:] for row in item_rows}
    documents: list[str] = []
    missing_metadata = 0
    for item_id in item_ids:
        title, genres, tags = metadata.get(item_id, (None, [], []))
        if item_id not in metadata:
            missing_metadata += 1
        values = [str(title)] if title else []
        values.extend(str(value) for value in (genres or []))
        values.extend(str(value) for value in (tags or []))
        documents.append(" ".join(values))
    started = time.perf_counter()
    vectorizer = TfidfVectorizer(
        lowercase=True,
        strip_accents="unicode",
        token_pattern=r"(?u)\b\w+\b",
        ngram_range=(1, 2),
        min_df=2,
        max_features=50_000,
        sublinear_tf=True,
        norm="l2",
        dtype=np.float32,
    )
    features = vectorizer.fit_transform(documents).tocsr()
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    working = feature_path.with_name(f"{feature_path.name}.part.npz")
    sp.save_npz(working, features, compressed=True)
    working.replace(feature_path)
    item_index_path = feature_path.with_suffix(".items.json")
    item_index_path.write_text(json.dumps(item_ids, separators=(",", ":")) + "\n", encoding="utf-8")
    report = {
        "model": "static_metadata_tfidf",
        "matrix_kind": "content_tfidf",
        "experiment": "static metadata future review-interaction ranking",
        "metadata_snapshot": "historical source snapshot without an as-of timestamp",
        "training_split_sha256": train_hash,
        "split_manifest_sha256": manifest["split_manifest_sha256"],
        "training_user_count": int(user_count),
        "training_event_count": int(event_count),
        "catalog_item_count": len(item_ids),
        "missing_metadata_count": missing_metadata,
        "feature_count": int(features.shape[1]),
        "feature_nnz": int(features.nnz),
        "max_features": 50_000,
        "ngram_range": [1, 2],
        "runtime_seconds": time.perf_counter() - started,
        "similarity_path": str(feature_path.resolve()),
        "similarity_sha256": _sha256(feature_path),
        "item_index_path": str(item_index_path.resolve()),
        "item_index_sha256": _sha256(item_index_path),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_report = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary_report.replace(report_path)
    return report
