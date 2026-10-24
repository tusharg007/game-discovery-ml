from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID


class LocalEventStore:
    """Directory-backed store for local tests; do not use as ephemeral cloud persistence."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.purge_expired()

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Apply the local adapter's 30-day receipt-time retention period."""
        cutoff = (now or datetime.now(UTC)) - timedelta(days=30)
        removed = 0
        for path in self.directory.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                received_at = datetime.fromisoformat(record["received_at"])
                if received_at.tzinfo is None:
                    received_at = received_at.replace(tzinfo=UTC)
                if received_at < cutoff:
                    path.unlink()
                    removed += 1
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return removed

    def _path(self, event_id: str) -> Path:
        safe_id = str(UUID(event_id))
        return self.directory / f"{safe_id}.json"

    def put_if_absent(self, event_id: str, record: dict[str, Any]) -> bool:
        destination = self._path(event_id)
        fd, temporary_name = tempfile.mkstemp(prefix=".event-", suffix=".part", dir=self.directory)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary_path, destination)
            except FileExistsError:
                return False
            return True
        finally:
            temporary_path.unlink(missing_ok=True)

    def get(self, event_id: str) -> dict[str, Any] | None:
        path = self._path(event_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
