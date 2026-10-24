from __future__ import annotations

from typing import Any, Protocol


class EventStore(Protocol):
    """Small immutable event store with create-if-absent semantics."""

    def put_if_absent(self, event_id: str, record: dict[str, Any]) -> bool:
        """Persist a new event and return False when the ID already exists."""

    def get(self, event_id: str) -> dict[str, Any] | None:
        """Read a persisted event by ID."""
