from __future__ import annotations

import ast
import gzip
import hashlib
import hmac
import json
import secrets
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_AST_NODES = 100_000
MAX_AST_DEPTH = 64
INTERACTION_SCHEMA = pa.schema(
    [
        ("user_key", pa.string()),
        ("item_id", pa.string()),
        ("event_date", pa.date32()),
        ("event_type", pa.string()),
        ("source_row_hash", pa.string()),
        ("source_file_hash", pa.string()),
    ]
)
ITEM_SCHEMA = pa.schema(
    [
        ("item_id", pa.string()),
        ("title", pa.string()),
        ("genres", pa.list_(pa.string())),
        ("tags", pa.list_(pa.string())),
        ("release_date", pa.date32()),
        ("metadata_snapshot", pa.string()),
        ("metadata_missing", pa.bool_()),
    ]
)


@dataclass(frozen=True)
class ParsedRecord:
    value: dict[str, Any] | None
    reason: str | None


def _check_ast_limits(tree: ast.AST) -> None:
    stack: list[tuple[ast.AST, int]] = [(tree, 0)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > MAX_AST_NODES:
            raise ValueError("literal_too_many_nodes")
        if depth > MAX_AST_DEPTH:
            raise ValueError("literal_too_deep")
        stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))


def parse_mapping_line(raw: bytes) -> ParsedRecord:
    if len(raw) > MAX_LINE_BYTES:
        return ParsedRecord(None, "line_too_long")
    try:
        line = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return ParsedRecord(None, "invalid_utf8")
    if not line:
        return ParsedRecord(None, "empty_line")
    try:
        value = json.loads(line)
    except (json.JSONDecodeError, RecursionError):
        try:
            tree = ast.parse(line, mode="eval")
            _check_ast_limits(tree)
            value = ast.literal_eval(tree)
        except (SyntaxError, ValueError, TypeError, RecursionError, MemoryError):
            return ParsedRecord(None, "malformed_record")
    if not isinstance(value, dict):
        return ParsedRecord(None, "record_not_object")
    return ParsedRecord(value, None)


def _get_event_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _identity_key(username: str, secret: bytes) -> str:
    return hmac.new(secret, username.encode("utf-8"), hashlib.sha256).hexdigest()


def load_or_create_identity_secret(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        secret = path.read_bytes()
        if len(secret) != 32:
            raise ValueError(f"Invalid private identity secret length in {path}")
        return secret
    secret = secrets.token_bytes(32)
    try:
        with path.open("xb") as output:
            output.write(secret)
    except FileExistsError:
        return load_or_create_identity_secret(path)
    return secret


def iter_interactions(
    raw_path: Path, source_file_hash: str, identity_secret: bytes
) -> Iterator[tuple[dict[str, Any] | None, str | None, bytes]]:
    with gzip.open(raw_path, "rb") as source:
        for raw in source:
            parsed = parse_mapping_line(raw)
            if parsed.reason:
                yield None, parsed.reason, raw
                continue
            record = parsed.value or {}
            username = record.get("username")
            item_id = record.get("product_id")
            if not isinstance(username, str) or not username.strip():
                yield None, "missing_username", raw
                continue
            if (
                item_id is None
                or isinstance(item_id, (dict, list, bool))
                or not str(item_id).strip()
            ):
                yield None, "missing_item_id", raw
                continue
            event_date = _get_event_date(record.get("date"))
            if event_date is None:
                reason = "missing_date" if record.get("date") in (None, "") else "invalid_date"
                yield None, reason, raw
                continue
            yield (
                {
                    "user_key": _identity_key(username, identity_secret),
                    "item_id": str(item_id).strip(),
                    "event_date": event_date,
                    "event_type": "review",
                    "source_row_hash": hashlib.sha256(raw).hexdigest(),
                    "source_file_hash": source_file_hash,
                },
                None,
                raw,
            )


def prepare_interactions(
    raw_path: Path,
    output_path: Path,
    quarantine_path: Path,
    identity_secret_path: Path,
    source_file_hash: str,
    batch_size: int = 20_000,
    progress_interval: int = 250_000,
) -> dict[str, int]:
    secret = load_or_create_identity_secret(identity_secret_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    working_path = output_path.with_name(f"{output_path.name}.part")
    quarantine_working_path = quarantine_path.with_name(f"{quarantine_path.name}.part")
    working_path.unlink(missing_ok=True)
    quarantine_working_path.unlink(missing_ok=True)
    counts: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    writer: pq.ParquetWriter | None = None
    started = time.monotonic()
    with gzip.open(quarantine_working_path, "wb") as quarantine:
        try:
            for index, (row, reason, raw) in enumerate(
                iter_interactions(raw_path, source_file_hash, secret), start=1
            ):
                if reason:
                    counts[reason] += 1
                    quarantine.write(raw if raw.endswith(b"\n") else raw + b"\n")
                else:
                    rows.append(row or {})
                    counts["valid_interaction_rows"] += 1
                    if len(rows) >= batch_size:
                        table = pa.Table.from_pylist(rows, schema=INTERACTION_SCHEMA)
                        if writer is None:
                            writer = pq.ParquetWriter(
                                working_path, INTERACTION_SCHEMA, compression="zstd"
                            )
                        writer.write_table(table)
                        rows.clear()
                if index % progress_interval == 0:
                    quarantined = sum(
                        value for key, value in counts.items() if key != "valid_interaction_rows"
                    )
                    print(
                        f"parsed review records={index:,} "
                        f"valid={counts['valid_interaction_rows']:,} quarantined={quarantined:,} "
                        f"elapsed_seconds={time.monotonic() - started:.0f}",
                        flush=True,
                    )
            if rows:
                table = pa.Table.from_pylist(rows, schema=INTERACTION_SCHEMA)
                if writer is None:
                    writer = pq.ParquetWriter(working_path, INTERACTION_SCHEMA, compression="zstd")
                writer.write_table(table)
        finally:
            if writer is not None:
                writer.close()
    if writer is None:
        pq.write_table(pa.Table.from_pylist([], schema=INTERACTION_SCHEMA), working_path)
    working_path.replace(output_path)
    quarantine_working_path.replace(quarantine_path)
    return dict(counts)


def _clean_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        return []
    clean = {str(item).strip() for item in values if isinstance(item, (str, int, float))}
    return sorted(item for item in clean if item)


def prepare_items(raw_path: Path, output_path: Path, metadata_snapshot: str) -> dict[str, int]:
    """Read catalog metadata, resolving duplicate IDs by sorted canonical record."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    chosen: dict[str, dict[str, Any]] = {}
    signatures: dict[str, set[str]] = {}
    counts: Counter[str] = Counter()
    with gzip.open(raw_path, "rb") as source:
        for raw in source:
            parsed = parse_mapping_line(raw)
            if parsed.reason:
                counts[parsed.reason] += 1
                continue
            item = parsed.value or {}
            item_id = item.get("id")
            if (
                item_id is None
                or isinstance(item_id, (dict, list, bool))
                or not str(item_id).strip()
            ):
                counts["missing_item_id"] += 1
                continue
            key = str(item_id).strip()
            title = item.get("title") or item.get("app_name") or ""
            title = str(title).strip() if isinstance(title, (str, int, float)) else ""
            release_date = _get_event_date(item.get("release_date"))
            metadata_missing = not bool(
                title
                or _clean_string_list(item.get("genres"))
                or _clean_string_list(item.get("tags"))
                or release_date
            )
            normalized = {
                "item_id": key,
                "title": title or "Unknown historical game",
                "genres": _clean_string_list(item.get("genres")),
                "tags": _clean_string_list(item.get("tags")),
                "release_date": release_date,
                "metadata_snapshot": metadata_snapshot,
                "metadata_missing": metadata_missing,
            }
            canonical = json.dumps(
                {**normalized, "release_date": release_date.isoformat() if release_date else None},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            signatures.setdefault(key, set()).add(canonical)
            if key not in chosen or canonical < json.dumps(
                {
                    **chosen[key],
                    "release_date": chosen[key]["release_date"].isoformat()
                    if chosen[key]["release_date"]
                    else None,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ):
                chosen[key] = normalized
            counts["metadata_rows"] += 1
    conflict_count = sum(len(variants) > 1 for variants in signatures.values())
    counts["metadata_conflicting_item_ids"] = conflict_count
    counts["metadata_unique_items"] = len(chosen)
    rows = [chosen[item_id] for item_id in sorted(chosen)]
    table = pa.Table.from_pylist(rows, schema=ITEM_SCHEMA)
    working_path = output_path.with_name(f"{output_path.name}.part")
    pq.write_table(table, working_path, compression="zstd")
    working_path.replace(output_path)
    return dict(counts)
