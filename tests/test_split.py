from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from game_discovery.data.split import choose_global_cutoffs, freeze_global_split


def test_cutoffs_use_whole_dates_at_approximate_quantiles():
    start = date(2020, 1, 1)
    daily = [(start + timedelta(days=day), 10) for day in range(10)]
    assert choose_global_cutoffs(daily) == (start + timedelta(days=6), start + timedelta(days=8))


def test_freeze_global_split_has_no_same_date_leakage_and_is_immutable(tmp_path: Path):
    start = date(2020, 1, 1)
    rows = []
    for day in range(10):
        for event in range(10):
            rows.append(
                {
                    "user_key": f"u-{event}",
                    "item_id": f"i-{event}",
                    "event_date": start + timedelta(days=day),
                    "event_type": "review",
                    "source_row_hash": f"{day}-{event}",
                    "source_file_hash": "a" * 64,
                }
            )
    source = tmp_path / "portfolio.parquet"
    pq.write_table(pa.Table.from_pylist(rows), source)
    split_dir = tmp_path / "splits"
    manifest_path = tmp_path / "split_manifest.json"
    manifest = freeze_global_split(source, split_dir, manifest_path)
    assert manifest["cutoff_a"] == "2020-01-07"
    assert manifest["cutoff_b"] == "2020-01-09"
    connection = duckdb.connect()
    train = connection.execute(
        f"SELECT min(event_date), max(event_date) FROM read_parquet('{(split_dir / 'train.parquet').as_posix()}')"
    ).fetchone()
    validation = connection.execute(
        f"SELECT min(event_date), max(event_date) FROM read_parquet('{(split_dir / 'validation.parquet').as_posix()}')"
    ).fetchone()
    test = connection.execute(
        f"SELECT min(event_date), max(event_date) FROM read_parquet('{(split_dir / 'test.parquet').as_posix()}')"
    ).fetchone()
    connection.close()
    assert train == (start, start + timedelta(days=5))
    assert validation == (start + timedelta(days=6), start + timedelta(days=7))
    assert test == (start + timedelta(days=8), start + timedelta(days=9))
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["split_manifest_sha256"]
    with pytest.raises(FileExistsError):
        freeze_global_split(source, split_dir, manifest_path)
