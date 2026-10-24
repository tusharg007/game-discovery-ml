from __future__ import annotations

import gzip
import json
from pathlib import Path

import pyarrow.parquet as pq

from game_discovery.data.parse import (
    parse_mapping_line,
    prepare_interactions,
    prepare_items,
)
from game_discovery.data.quality import prepare_quality


def test_parser_accepts_json_and_python_literal_without_eval():
    assert parse_mapping_line(b'{"username":"u","product_id":"1"}').value == {
        "username": "u",
        "product_id": "1",
    }
    assert parse_mapping_line(b"{'username': 'u', 'product_id': '1'}").value == {
        "username": "u",
        "product_id": "1",
    }
    assert parse_mapping_line(b"__import__('os').system('whoami')").reason == "malformed_record"
    assert parse_mapping_line(b"x" * (2 * 1024 * 1024 + 1)).reason == "line_too_long"


def test_prepare_pipeline_counts_deduplicates_and_keeps_user_fields_private(tmp_path: Path):
    raw_dir = tmp_path / "data/raw"
    processed = tmp_path / "data/processed"
    private = tmp_path / "private"
    artifacts = tmp_path / "artifacts"
    raw_dir.mkdir(parents=True)
    review_lines = [
        {
            "username": "private-user-a",
            "product_id": "10",
            "date": "2020-01-01",
            "text": "private review",
        },
        {"username": "private-user-a", "product_id": "10", "date": "2020-02-01", "text": "later"},
        {"username": "private-user-b", "product_id": "20", "date": "2020-03-01", "text": "hidden"},
        {"username": "private-user-c", "product_id": "999", "date": "2020-04-01", "text": "orphan"},
        {"username": "private-user-d", "product_id": "30", "date": "bad", "text": "bad date"},
    ]
    reviews_path = raw_dir / "steam_reviews.json.gz"
    with gzip.open(reviews_path, "wb") as stream:
        for row in review_lines:
            stream.write(json.dumps(row).encode() + b"\n")
        stream.write(b"not a record\n")
    games_path = raw_dir / "steam_games.json.gz"
    with gzip.open(games_path, "wb") as stream:
        stream.write(
            json.dumps({"id": "10", "title": "Game A", "genres": ["Indie"]}).encode() + b"\n"
        )
        stream.write(
            json.dumps({"id": "20", "title": "Game B", "tags": ["Puzzle"]}).encode() + b"\n"
        )

    interactions_raw = processed / "interactions_raw.parquet"
    parse_counts = prepare_interactions(
        reviews_path,
        interactions_raw,
        private / "quarantine.jsonl.gz",
        private / "mappings/user.key",
        "a" * 64,
        batch_size=2,
    )
    assert parse_counts["valid_interaction_rows"] == 4
    assert parse_counts["invalid_date"] == 1
    assert parse_counts["malformed_record"] == 1

    items_raw = processed / "items_raw.parquet"
    metadata_counts = prepare_items(games_path, items_raw, "b" * 64)
    _, stats = prepare_quality(
        interaction_rows_path=interactions_raw,
        items_path=items_raw,
        cleaned_interactions_path=processed / "cleaned/interactions.parquet",
        cleaned_items_path=processed / "cleaned/items.parquet",
        sampled_interactions_path=processed / "full/interactions.parquet",
        config={"mode": "full", "sampling": {}},
        parse_counts=parse_counts,
        metadata_counts=metadata_counts,
        quality_output=artifacts / "data_quality.json",
        stats_output=artifacts / "dataset_stats.json",
        profile_output=artifacts / "data_profile.html",
    )

    assert stats["full_cleaned_events"] == 3
    assert stats["full_cleaned_users"] == 3
    assert stats["sample_events"] == 3
    clean = pq.read_table(processed / "cleaned/interactions.parquet")
    assert clean.column_names == [
        "user_key",
        "item_id",
        "event_date",
        "event_type",
        "source_row_hash",
        "source_file_hash",
    ]
    assert "private-user-a" not in str(clean.to_pylist())
    assert "private review" not in str(clean.to_pylist())
    catalog = pq.read_table(processed / "cleaned/items.parquet").to_pylist()
    orphan = next(item for item in catalog if item["item_id"] == "999")
    assert orphan["title"] == "Unknown historical game"
    assert orphan["metadata_missing"] is True
