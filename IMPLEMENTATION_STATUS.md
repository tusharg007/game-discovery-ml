# Implementation Status

Updated: 2026-10-24 (Asia/Calcutta)

Source plan: `E:\Game Discovery\GAME_DISCOVERY_IMPLEMENTATION_PLAN.md` (kept outside this separate repository).

## Current milestone: M2 — Honest evaluation

M0 and M1 have passed their local gates. No model training or evaluation has been run.

## M0 — Bootstrap

- Created a separate Git repository at `E:\Game Discovery\game-discovery-ml`; initial commit: `ecb9611` (`Bootstrap game discovery project`).
- Added Python package metadata, serving/training/dev dependency groups and `uv.lock`.
- Python 3.11.9 and `uv` 0.13.5 used; `uv sync --extra train --extra dev` installed 46 packages.
- CLI smoke: `uv run game-discovery doctor` reported ready on Python 3.11.9.
- M0 checks: `uv run pytest` (1 passed), `uv run ruff check .` and `uv run ruff format --check .` (passed).
- Docker Desktop 4.85.0 / Linux amd64 engine 29.6.2 is available. `npm` is broken and is not needed before the later frontend milestone.
- E: had approximately 35.5 GB free initially; approximately 33.7 GiB remained after dataset acquisition and preparation.

## M1 — Real data

### Source and integrity

- Commands: `uv run game-discovery data download --config configs/portfolio.yaml --source auto`; then `uv run game-discovery data prepare --config configs/portfolio.yaml`.
- The publisher host failed standard TLS verification because its certificate was expired. The downloader used the plan-pinned mirror at revision `8e9c6b569122fb20668f5da3b0f3970a853fc5d8` over verified HTTPS.
- Both files matched the pinned repository API's LFS SHA-256 and passed a full gzip read. Exact source URLs, safe redirect destinations, bytes, hashes, revision, timestamps, ETags and publisher failure are in ignored `artifacts/manifests/source_manifest.json`.
- This verifies bytes against the pinned mirror only; equivalence to publisher files has not been independently established.

### Actual processing evidence

- Full review file: 1,338,063,248 compressed bytes; 7,793,069 valid timestamped events; 0 malformed/rejected records and 0 invalid event dates.
- Earliest user-item deduplication removed 903,341 later duplicate events, leaving 6,889,728 events across 2,567,538 username-proxy identities and 15,474 interacted items.
- Metadata: 32,133 source rows, 2 rows without IDs, 32,132 unique item IDs; no conflicting IDs. Every interacted item has metadata.
- Portfolio sample: stable SHA-256 threshold selected 100,134 users at fraction 0.0389478169; all 267,534 valid events for selected users retained across 9,792 items.
- Full snapshot sparsity: 99.9827%. Top 1% of items account for 36.35% of events, top 10% for 82.85%, and bottom 80% for 7.70%.
- Events span 2010-10-15 to 2018-01-05. Metadata is an untimestamped historical snapshot.
- Generated locally: source/quality/stats/preparation manifests, `data_profile.html`, typed raw/cleaned Parquet and portfolio Parquet. Raw, user-level and data-derived artifacts remain ignored/local pending permission review.
- `uv run pytest --basetemp tests/.pytest-tmp -q` — 3 passed; `uv run ruff check .` and `uv run ruff format --check .` — passed.

### Outstanding data/publication gate

The UCSD page requests citation but does not state an explicit redistribution license. Source data and derived reports are local only. Prepared interactions exclude Steam usernames and review text; the private HMAC key and malformed-line quarantine are also local and ignored. Resolve publication rights before publishing data-derived artifacts. No Azure account was inspected or changed.

## Next actions

1. Freeze chronological cutoffs from the portfolio sample before model evaluation; write and hash the split manifest.
2. Implement hand-checked ranking metrics and uniform, global-popularity and recent-popularity baselines on identical users/catalogs.
3. Keep validation and final-test data separated; do not inspect test results before a selection record is frozen.

## Evidence integrity

No evaluation scores, model results, UI screenshots, resource IDs, actual cloud costs, deployment URL or cloud verification are claimed.
