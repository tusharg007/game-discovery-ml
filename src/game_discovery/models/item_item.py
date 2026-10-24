from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import scipy.sparse as sp


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def train_item_item(
    train_path: Path,
    split_manifest_path: Path,
    artifact_path: Path,
    report_path: Path,
    *,
    shrinkage: float = 20.0,
    max_neighbors: int = 200,
) -> dict[str, Any]:
    """Fit binary item-item cosine similarity with count shrinkage from train events only."""
    if shrinkage < 0 or max_neighbors < 1:
        raise ValueError("shrinkage must be non-negative and max_neighbors must be positive")
    manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    train_hash = _sha256(train_path)
    if train_hash != manifest["partitions"]["train"]["parquet_sha256"]:
        raise RuntimeError("Training input does not match the frozen split manifest")
    source = "'" + train_path.resolve().as_posix().replace("'", "''") + "'"
    connection = duckdb.connect()
    rows = connection.execute(
        f"SELECT user_key, item_id FROM read_parquet({source}) ORDER BY user_key, item_id"
    ).fetchall()
    connection.close()
    users = sorted({str(user) for user, _ in rows})
    items = sorted({str(item) for _, item in rows})
    user_index = {user: index for index, user in enumerate(users)}
    item_index = {item: index for index, item in enumerate(items)}
    user_rows = np.fromiter((user_index[str(user)] for user, _ in rows), dtype=np.int32)
    item_cols = np.fromiter((item_index[str(item)] for _, item in rows), dtype=np.int32)
    interactions = sp.csr_matrix(
        (np.ones(len(rows), dtype=np.float32), (user_rows, item_cols)),
        shape=(len(users), len(items)),
    )
    started = time.perf_counter()
    incidence = interactions.T.tocsr()
    cooccurrence = (incidence @ incidence.T).tocsr()
    supports = np.asarray(incidence.sum(axis=1)).ravel().astype(np.float64)
    cooccurrence.setdiag(0)
    cooccurrence.eliminate_zeros()
    similarity_rows: list[int] = []
    similarity_cols: list[int] = []
    similarity_values: list[float] = []
    item_id_array = np.asarray(items, dtype=object)
    for row in range(len(items)):
        start, end = cooccurrence.indptr[row : row + 2]
        cols = cooccurrence.indices[start:end]
        counts = cooccurrence.data[start:end].astype(np.float64)
        if not len(cols):
            continue
        scores = counts / np.sqrt(supports[row] * supports[cols])
        scores *= counts / (counts + shrinkage) if shrinkage else 1.0
        order = np.lexsort((item_id_array[cols], -scores))
        if len(order) > max_neighbors:
            order = order[:max_neighbors]
        similarity_rows.extend([row] * len(order))
        similarity_cols.extend(cols[order].tolist())
        similarity_values.extend(scores[order].astype(np.float32).tolist())
    similarity = sp.csr_matrix(
        (similarity_values, (similarity_rows, similarity_cols)),
        shape=(len(items), len(items)),
        dtype=np.float32,
    )
    similarity.sort_indices()
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    working = artifact_path.with_name(f"{artifact_path.name}.part.npz")
    sp.save_npz(working, similarity, compressed=True)
    working.replace(artifact_path)
    item_index_path = artifact_path.with_suffix(".items.json")
    item_index_path.write_text(json.dumps(items, separators=(",", ":")) + "\n", encoding="utf-8")
    report = {
        "model": "item_item_cosine_shrinkage",
        "experiment": "future review-interaction ranking",
        "training_split_sha256": train_hash,
        "split_manifest_sha256": manifest["split_manifest_sha256"],
        "training_user_count": len(users),
        "training_item_count": len(items),
        "training_event_count": len(rows),
        "similarity_nnz": int(similarity.nnz),
        "shrinkage": shrinkage,
        "max_neighbors_per_item": max_neighbors,
        "runtime_seconds": time.perf_counter() - started,
        "similarity_path": str(artifact_path.resolve()),
        "similarity_sha256": _sha256(artifact_path),
        "item_index_path": str(item_index_path.resolve()),
        "item_index_sha256": _sha256(item_index_path),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(report_path)
    return report
