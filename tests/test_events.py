from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from game_discovery.events.local import LocalEventStore
from game_discovery.events.tokens import (
    InvalidImpressionToken,
    create_impression_token,
    verify_impression_token,
)


def test_impression_token_binds_items_expiry_and_secret_rotation():
    secret = b"s" * 32
    token = create_impression_token(
        secret=secret,
        model_version="fixture-v1",
        item_ids=["1", "2"],
        ttl_seconds=60,
        now=1000,
    )
    payload = verify_impression_token(token, secret=secret, item_id="2", now=1030)
    assert payload["model_version"] == "fixture-v1"
    with pytest.raises(InvalidImpressionToken, match="not part"):
        verify_impression_token(token, secret=secret, item_id="3", now=1030)
    with pytest.raises(InvalidImpressionToken, match="expired"):
        verify_impression_token(token, secret=secret, item_id="1", now=1061)
    with pytest.raises(InvalidImpressionToken, match="signature"):
        verify_impression_token(token, secret=b"r" * 32, item_id="1", now=1030)
    with pytest.raises(ValueError, match="32 bytes"):
        create_impression_token(secret=b"short", model_version="v1", item_ids=["1"])


def test_local_store_create_is_atomic_and_survives_a_new_instance(tmp_path: Path):
    directory = tmp_path / "events"
    event_id = str(uuid4())
    record = {"event_id": event_id, "received_at": datetime.now(UTC).isoformat()}

    def write_once() -> bool:
        return LocalEventStore(directory).put_if_absent(event_id, record)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: write_once(), range(8)))
    assert sum(results) == 1
    restarted = LocalEventStore(directory)
    assert restarted.put_if_absent(event_id, {"different": "body"}) is False
    assert restarted.get(event_id) == record


def test_local_store_applies_30_day_receipt_retention(tmp_path: Path):
    directory = tmp_path / "events"
    directory.mkdir()
    stale_id = str(uuid4())
    stale_time = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    (directory / f"{stale_id}.json").write_text(
        json.dumps({"event_id": stale_id, "received_at": stale_time}), encoding="utf-8"
    )
    store = LocalEventStore(directory)
    assert store.get(stale_id) is None
