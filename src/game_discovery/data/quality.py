from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import duckdb


def _sql_path(path: Path) -> str:
    return "'" + path.resolve().as_posix().replace("'", "''") + "'"


def _json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def _profile_html(quality: dict[str, Any], stats: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = [(key, value) for key, value in quality.items()]
    stats_rows = [(key, value) for key, value in stats.items()]
    quality_html = "\n".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in rows
    )
    stats_html = "\n".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in stats_rows
    )
    content = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Steam interaction data profile</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%;margin-bottom:2rem}}th,td{{text-align:left;border-bottom:1px solid #ddd;padding:.45rem}}
th{{width:45%}}small{{color:#555}}</style><body>
<h1>Steam review interaction data profile</h1>
<p>Aggregated profile only. It contains no usernames, review text, or per-user histories.</p>
<h2>Quality checks</h2><table>{quality_html}</table>
<h2>Dataset statistics</h2><table>{stats_html}</table>
<small>Counts describe the downloaded version and selected sample recorded in this repository's private manifests.</small>
</body></html>"""
    output.write_text(content, encoding="utf-8")


def _activity_stats(connection: duckdb.DuckDBPyConnection, interactions: Path) -> dict[str, Any]:
    source = _sql_path(interactions)
    user = connection.execute(
        f"""WITH c AS (SELECT user_key, count(*) AS n FROM read_parquet({source}) GROUP BY user_key)
        SELECT count(*), min(n), quantile_cont(n, 0.5), quantile_cont(n, 0.9),
               quantile_cont(n, 0.99), max(n),
               sum(CASE WHEN n=1 THEN 1 ELSE 0 END),
               sum(CASE WHEN n BETWEEN 2 AND 9 THEN 1 ELSE 0 END),
               sum(CASE WHEN n>=10 THEN 1 ELSE 0 END)
        FROM c"""
    ).fetchone()
    item = connection.execute(
        f"""WITH c AS (SELECT item_id, count(*) AS n FROM read_parquet({source}) GROUP BY item_id),
        ranked AS (SELECT n, row_number() OVER (ORDER BY n DESC, item_id) AS rank,
                   count(*) OVER () AS items, sum(n) OVER () AS interactions FROM c)
        SELECT count(*), min(n), quantile_cont(n, 0.5), quantile_cont(n, 0.9),
               quantile_cont(n, 0.99), max(n),
               sum(CASE WHEN rank <= ceil(items * 0.01) THEN n ELSE 0 END) / max(interactions),
               sum(CASE WHEN rank <= ceil(items * 0.10) THEN n ELSE 0 END) / max(interactions),
               sum(CASE WHEN rank > items * 0.20 THEN n ELSE 0 END) / max(interactions)
        FROM ranked"""
    ).fetchone()
    dates = connection.execute(
        f"SELECT min(event_date), max(event_date) FROM read_parquet({source})"
    ).fetchone()
    return {
        "users": user[0],
        "user_events_min": user[1],
        "user_events_median": user[2],
        "user_events_p90": user[3],
        "user_events_p99": user[4],
        "user_events_max": user[5],
        "users_with_1_event": user[6],
        "users_with_2_to_9_events": user[7],
        "users_with_10_plus_events": user[8],
        "items": item[0],
        "item_events_min": item[1],
        "item_events_median": item[2],
        "item_events_p90": item[3],
        "item_events_p99": item[4],
        "item_events_max": item[5],
        "top_1_percent_item_event_share": item[6],
        "top_10_percent_item_event_share": item[7],
        "bottom_80_percent_item_event_share": item[8],
        "first_event_date": dates[0],
        "last_event_date": dates[1],
    }


def prepare_quality(
    interaction_rows_path: Path,
    items_path: Path,
    cleaned_interactions_path: Path,
    cleaned_items_path: Path,
    sampled_interactions_path: Path,
    config: dict[str, Any],
    parse_counts: dict[str, int],
    metadata_counts: dict[str, int],
    quality_output: Path,
    stats_output: Path,
    profile_output: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    for path in (cleaned_interactions_path, cleaned_items_path, sampled_interactions_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
    connection = duckdb.connect()
    interaction_source = _sql_path(interaction_rows_path)
    items_source = _sql_path(items_path)
    cleaned_source = _sql_path(cleaned_interactions_path)
    clean_items_source = _sql_path(cleaned_items_path)
    sampled_source = _sql_path(sampled_interactions_path)

    raw_rows = connection.execute(
        f"SELECT count(*) FROM read_parquet({interaction_source})"
    ).fetchone()[0]
    source_duplicate_rows = connection.execute(
        f"SELECT count(*) - count(DISTINCT source_row_hash) FROM read_parquet({interaction_source})"
    ).fetchone()[0]
    pair_surplus = connection.execute(
        f"""SELECT count(*) - count(DISTINCT (user_key, item_id))
            FROM read_parquet({interaction_source})"""
    ).fetchone()[0]
    connection.execute(
        f"""COPY (
            SELECT user_key, item_id, event_date, event_type, source_row_hash, source_file_hash
            FROM read_parquet({interaction_source})
            QUALIFY row_number() OVER (
                PARTITION BY user_key, item_id ORDER BY event_date, source_row_hash
            ) = 1
        ) TO {cleaned_source} (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )

    orphan_count = connection.execute(
        f"""SELECT count(*) FROM read_parquet({cleaned_source}) i
            LEFT JOIN read_parquet({items_source}) m USING (item_id)
            WHERE m.item_id IS NULL"""
    ).fetchone()[0]
    if orphan_count:
        missing_items_path = cleaned_items_path.with_name(
            f"{cleaned_items_path.stem}.missing.parquet"
        )
        missing_items_path.unlink(missing_ok=True)
        missing_items_source = _sql_path(missing_items_path)
        connection.execute(
            f"""COPY (
                SELECT DISTINCT i.item_id, 'Unknown historical game' AS title,
                       []::VARCHAR[] AS genres, []::VARCHAR[] AS tags,
                       NULL::DATE AS release_date, 'no-metadata' AS metadata_snapshot,
                       TRUE AS metadata_missing
                FROM read_parquet({cleaned_source}) i
                LEFT JOIN read_parquet({items_source}) m USING (item_id)
                WHERE m.item_id IS NULL
            ) TO {missing_items_source} (FORMAT PARQUET, COMPRESSION ZSTD)"""
        )
        connection.execute(
            f"""COPY (
                SELECT * FROM read_parquet({items_source})
                UNION ALL SELECT * FROM read_parquet({missing_items_source})
            ) TO {clean_items_source} (FORMAT PARQUET, COMPRESSION ZSTD)"""
        )
        missing_items_path.unlink(missing_ok=True)
    else:
        connection.execute(
            f"COPY (SELECT * FROM read_parquet({items_source})) TO {clean_items_source} "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )

    full_stats = _activity_stats(connection, cleaned_interactions_path)
    total_events = connection.execute(
        f"SELECT count(*) FROM read_parquet({cleaned_source})"
    ).fetchone()[0]
    total_users = int(full_stats["users"])
    sampling = config.get("sampling", {})
    mode = str(config.get("mode", "smoke"))
    if mode == "full":
        fraction = 1.0
    elif mode == "portfolio":
        target_users = int(sampling.get("target_users") or 100_000)
        fraction = min(1.0, target_users / total_users) if total_users else 1.0
    else:
        fraction = float(sampling.get("fraction", 0.01))
    if not (0 < fraction <= 1):
        raise ValueError(f"Sampling fraction must be in (0, 1], got {fraction}")
    threshold = int(fraction * (16**15))
    connection.execute(
        f"""COPY (
            SELECT * FROM read_parquet({cleaned_source})
            WHERE cast(('0x' || substr(sha256(user_key), 1, 15)) AS UBIGINT) < {threshold}
        ) TO {sampled_source} (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )
    sample_stats = (
        _activity_stats(connection, sampled_interactions_path) if fraction < 1 else full_stats
    )
    sample_events = connection.execute(
        f"SELECT count(*) FROM read_parquet({sampled_source})"
    ).fetchone()[0]
    metadata_total = connection.execute(
        f"SELECT count(*) FROM read_parquet({clean_items_source})"
    ).fetchone()[0]
    metadata_missing = connection.execute(
        f"SELECT count(*) FROM read_parquet({clean_items_source}) WHERE metadata_missing"
    ).fetchone()[0]
    all_users_items = total_users * int(full_stats["items"])
    reason_keys = (
        "line_too_long",
        "invalid_utf8",
        "empty_line",
        "malformed_record",
        "record_not_object",
        "missing_username",
        "missing_item_id",
        "missing_date",
        "invalid_date",
    )
    parse_reason_counts = {reason: int(parse_counts.get(reason, 0)) for reason in reason_keys}
    quality = {
        "valid_interaction_rows_before_deduplication": raw_rows,
        "invalid_or_quarantined_records_by_reason": parse_reason_counts,
        "valid_interaction_rows": int(parse_counts.get("valid_interaction_rows", 0)),
        "item_metadata_record_counts": metadata_counts,
        "duplicate_source_rows": int(source_duplicate_rows),
        "duplicate_user_item_pairs_removed": int(pair_surplus),
        "deduplicated_interaction_rows": int(total_events),
        "metadata_conflicting_item_ids_resolved_deterministically": int(
            metadata_counts.get("metadata_conflicting_item_ids", 0)
        ),
        "orphan_interactions_retained_with_neutral_metadata": int(orphan_count),
        "invalid_event_dates": int(
            parse_counts.get("missing_date", 0) + parse_counts.get("invalid_date", 0)
        ),
    }
    stats = {
        "experiment_data_mode": mode,
        "sampling_method": "stable SHA-256 threshold on private HMAC user keys",
        "sampling_fraction": fraction,
        "sampling_bias_note": (
            "Users are selected uniformly by a stable hash threshold and all valid events for "
            "selected users are retained; sampled event volume therefore reflects user activity. "
            "The source username field is an identity proxy and may contain collisions or changes."
        ),
        "sample_users": sample_stats.get("users", 0),
        "sample_events": int(sample_events),
        "sample_items": sample_stats.get("items", 0),
        "full_cleaned_events": int(total_events),
        "full_cleaned_users": total_users,
        "full_cleaned_items": full_stats["items"],
        "user_item_sparsity": 1 - (int(total_events) / all_users_items)
        if all_users_items
        else None,
        "metadata_items": int(metadata_total),
        "metadata_items_missing": int(metadata_missing),
        "metadata_coverage": (metadata_total - metadata_missing) / metadata_total
        if metadata_total
        else None,
        **full_stats,
    }
    _json_write(quality_output, quality)
    _json_write(stats_output, stats)
    _profile_html(quality, stats, profile_output)
    connection.close()
    return quality, stats
