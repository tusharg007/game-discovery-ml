"""Bounded smoke of an owned local or HTTPS deployment; no offline evaluation or feedback writes."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path


def request(base: str, path: str, payload: dict | None = None) -> tuple[int, object, float]:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base + path, data=body, headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        raw = response.read()
        data = (
            json.loads(raw)
            if response.headers.get_content_type() == "application/json"
            else raw.decode()
        )
        return response.status, data, (time.perf_counter() - started) * 1000


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def smoke(base: str, expected_version: str, expected_catalog: str) -> dict:
    parsed = urllib.parse.urlsplit(base)
    require(
        parsed.scheme == "https" or parsed.hostname in {"127.0.0.1", "localhost"},
        "Use HTTPS or a loopback address",
    )
    require(
        not parsed.query and not parsed.username and not parsed.password,
        "Base URL cannot contain credentials or query parameters",
    )
    count = 0
    for path in ("/healthz", "/readyz", "/", "/static/assets/app.js", "/static/assets/index.css"):
        status, data, _ = request(base, path)
        count += 1
        require(status == 200, f"{path}: expected HTTP 200, got {status}")
        if path == "/readyz":
            require(data["model_version"] == expected_version, "Unexpected model version")
            require(data["catalog_version"] == expected_catalog, "Unexpected catalog version")
    status, info, _ = request(base, "/v1/model-info")
    count += 1
    require(status == 200 and info["feedback"]["enabled"] is False, "Feedback must be disabled")
    status, catalog, _ = request(base, "/v1/catalog?limit=20")
    count += 1
    require(status == 200 and len(catalog["items"]) == 20, "Expected at least 20 catalog items")
    ids = [row["item_id"] for row in catalog["items"]]
    status, tail, _ = request(base, "/v1/catalog?limit=20&sort=tail")
    count += 1
    require(status == 200, "Tail catalog request failed")
    tail_ids = [row["item_id"] for row in tail["items"]]
    profiles = [[], ids[:1], ids[:3], ids[:20], tail_ids[:3], ["unknown-render-smoke"]]

    def check_case(case: tuple[str, list[str]]) -> dict:
        model, seeds = case
        status, data, elapsed = request(
            base, "/v1/recommendations", {"model": model, "seed_item_ids": seeds, "k": 20}
        )
        require(status == 200, f"Recommendation failed: {model} HTTP {status}")
        recommendations = data["recommendations"]
        returned = [row["item_id"] for row in recommendations]
        require(
            len(returned) == len(set(returned)) and not set(seeds).intersection(returned),
            "Duplicates or seeds returned",
        )
        require(
            len(returned) <= 20 and data["feedback_enabled"] is False,
            "Invalid recommendation count or feedback state",
        )
        return {
            "model": model,
            "seed_count": len(seeds),
            "returned_count": len(returned),
            "fallback_reason": data.get("fallback_reason"),
            "latency_ms": elapsed,
        }

    cases = [
        (model, profile)
        for model in ("champion", "recent_popularity", "als")
        for profile in profiles
    ]
    results = [check_case(case) for case in cases]
    count += len(cases)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results.extend(pool.map(check_case, cases))
    count += len(cases)
    status, event, _ = request(base, "/v1/events", {})
    count += 1
    require(
        status == 503 and event.get("persisted") is False,
        "Disabled feedback must reject without persistence",
    )
    # Never probe public operational metrics as part of this smoke.
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "evidence_type": "HTTP smoke; synthetic visitor inputs against the actual item-only bundle",
        "base_url": base,
        "model_version": expected_version,
        "catalog_version": expected_catalog,
        "request_count": count,
        "maximum_concurrency": 5,
        "feedback_writes": 0,
        "passed": True,
        "cases": results,
        "limitation": "Small local smoke; not a cloud latency or stable tail-percentile benchmark.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:10000")
    parser.add_argument("--model-version", default="portfolio-hybrid-content-popularity-v1")
    parser.add_argument("--catalog-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = smoke(args.base_url.rstrip("/"), args.model_version, args.catalog_version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, indent=2))


if __name__ == "__main__":
    main()
