from __future__ import annotations

import gc
import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, Self

import duckdb
import numpy as np
import psutil
import scipy.sparse as sp
from threadpoolctl import threadpool_limits


@dataclass(frozen=True)
class ALSConfig:
    factors: int
    regularization: float
    confidence_alpha: float
    iterations: int = 20
    seed: int = 1729

    @property
    def name(self) -> str:
        reg = str(self.regularization).replace(".", "p")
        return f"als-f{self.factors}-r{reg}-a{self.confidence_alpha}-s{self.seed}"


ALS_GRID = tuple(
    ALSConfig(factors=factors, regularization=regularization, confidence_alpha=alpha)
    for factors in (32, 64)
    for regularization in (0.01, 0.1)
    for alpha in (10.0, 40.0)
)


def build_confidence_matrix(
    user_indices: np.ndarray,
    item_indices: np.ndarray,
    n_users: int,
    n_items: int,
    confidence_alpha: float,
) -> sp.csr_matrix:
    if confidence_alpha <= 0:
        raise ValueError("confidence_alpha must be positive")
    if len(user_indices) != len(item_indices):
        raise ValueError("user and item index arrays must have equal lengths")
    values = np.full(len(user_indices), 1.0 + confidence_alpha, dtype=np.float32)
    matrix = sp.coo_matrix(
        (values, (user_indices, item_indices)), shape=(n_users, n_items), dtype=np.float32
    ).tocsr()
    matrix.sum_duplicates()
    return matrix


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _PeakRSS:
    def __init__(self, interval: float = 0.1) -> None:
        self._process = psutil.Process(os.getpid())
        self._interval = interval
        self._stop = threading.Event()
        self.peak_bytes = self._process.memory_info().rss
        self._thread = threading.Thread(target=self._watch, daemon=True)

    def _watch(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.peak_bytes = max(self.peak_bytes, self._process.memory_info().rss)
            except psutil.Error:
                return

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._stop.set()
        self._thread.join()
        self.peak_bytes = max(self.peak_bytes, self._process.memory_info().rss)


def _loss_callback(losses: list[float]):
    def on_epoch(epoch: int, elapsed: float, loss: float | None) -> None:
        if loss is not None:
            losses.append(float(loss))

    return on_epoch


def train_als_grid(
    train_path: Path,
    split_manifest_path: Path,
    experiment_root: Path,
    report_path: Path,
    *,
    configs: tuple[ALSConfig, ...] = ALS_GRID,
) -> dict[str, Any]:
    """Train the bounded CPU grid; implicit receives explicit confidence values with alpha=1."""
    with threadpool_limits(limits=1, user_api="blas"):
        from implicit.als import AlternatingLeastSquares

        split_manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
        source = "'" + train_path.resolve().as_posix().replace("'", "''") + "'"
        connection = duckdb.connect()
        rows = connection.execute(
            f"SELECT user_key, item_id FROM read_parquet({source}) ORDER BY user_key, item_id"
        ).fetchall()
        connection.close()
        train_hash = _sha256(train_path)
        if train_hash != split_manifest["partitions"]["train"]["parquet_sha256"]:
            raise RuntimeError("Training input does not match the frozen split manifest")
        user_keys = sorted({str(user) for user, _ in rows})
        item_ids = sorted({str(item) for _, item in rows})
        user_index = {key: index for index, key in enumerate(user_keys)}
        item_index = {item: index for index, item in enumerate(item_ids)}
        row_indices = np.fromiter((user_index[user] for user, _ in rows), dtype=np.int32)
        col_indices = np.fromiter((item_index[item] for _, item in rows), dtype=np.int32)
        experiment_root.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []

        for config in configs:
            confidence = build_confidence_matrix(
                row_indices,
                col_indices,
                len(user_keys),
                len(item_ids),
                config.confidence_alpha,
            )
            epoch_losses: list[float] = []

            model = AlternatingLeastSquares(
                factors=config.factors,
                regularization=config.regularization,
                alpha=1.0,  # fit() multiplies stored values by alpha; leave explicit 1+alpha intact
                iterations=config.iterations,
                random_state=config.seed,
                num_threads=1,
                use_gpu=False,
                calculate_training_loss=True,
            )
            started = time.perf_counter()
            with _PeakRSS() as memory:
                model.fit(confidence, show_progress=False, callback=_loss_callback(epoch_losses))
            runtime = time.perf_counter() - started

            model_dir = experiment_root / config.name
            model_dir.mkdir(parents=True, exist_ok=True)
            factors_path = model_dir / "factors.npz"
            np.savez_compressed(
                factors_path,
                user_factors=np.asarray(model.user_factors, dtype=np.float32),
                item_factors=np.asarray(model.item_factors, dtype=np.float32),
                user_keys=np.asarray(user_keys, dtype=np.str_),
                item_ids=np.asarray(item_ids, dtype=np.str_),
            )
            results.append(
                {
                    **asdict(config),
                    "name": config.name,
                    "library": "implicit",
                    "library_version": version("implicit"),
                    "device": "cpu",
                    "library_alpha_multiplier": 1.0,
                    "stored_observed_confidence": 1.0 + config.confidence_alpha,
                    "fit_input_shape": list(confidence.shape),
                    "fit_input_nnz": int(confidence.nnz),
                    "training_data_sha256": train_hash,
                    "runtime_seconds": runtime,
                    "process_peak_rss_mib": memory.peak_bytes / (1024**2),
                    "final_training_loss": epoch_losses[-1] if epoch_losses else None,
                    "epoch_training_losses": epoch_losses,
                    "private_factors_path": str(factors_path),
                    "factors_sha256": _sha256(factors_path),
                }
            )
            print(
                f"trained {config.name} runtime_seconds={runtime:.1f} "
                f"peak_rss_mib={memory.peak_bytes / (1024**2):.1f} "
                f"final_loss={epoch_losses[-1] if epoch_losses else None}",
                flush=True,
            )
            del model, confidence
            gc.collect()

    report = {
        "experiment": "future review-interaction ranking",
        "training_split": str(train_path),
        "training_split_sha256": train_hash,
        "split_manifest_sha256": split_manifest["split_manifest_sha256"],
        "training_user_count": len(user_keys),
        "training_item_count": len(item_ids),
        "training_event_count": len(rows),
        "configuration_count": len(configs),
        "seed_policy": "fixed seed 1729 for every grid configuration",
        "confidence_convention": (
            "binary preference; stored confidence is 1 + configuration alpha; implicit.fit alpha=1.0"
        ),
        "thread_policy": "one implicit CPU thread and one BLAS thread",
        "configurations": results,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = report_path.with_suffix(report_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_path, report_path)
    return report
