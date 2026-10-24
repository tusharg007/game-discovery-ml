# Implementation Status

Updated: 2026-10-25 (Asia/Calcutta)

Source plan: `E:\Game Discovery\GAME_DISCOVERY_IMPLEMENTATION_PLAN.md` (kept outside this separate repository).

## Current milestone: M6 — Lifecycle

M0–M5 have passed locally. M3 selection was frozen before the single M4 final-test run. The product remains local and no cloud deployment is claimed.

## M0 — Bootstrap

- Created a separate Git repository at `E:\Game Discovery\game-discovery-ml`; initial commit: `ecb9611` (`Bootstrap game discovery project`).
- Added Python package metadata, serving/training/dev dependency groups and `uv.lock`.
- Python 3.11.9 and `uv` 0.13.5 used; `uv sync --extra train --extra dev` installed 46 packages.
- CLI smoke: `uv run game-discovery doctor` reported ready on Python 3.11.9.
- M0 checks: `uv run pytest` (1 passed), `uv run ruff check .` and `uv run ruff format --check .` (passed).
- Docker Desktop 4.85.0 / Linux amd64 engine 29.6.2 is available. The host npm shim was unavailable at M0; the later Vite build runs from a locked Node image in Docker.
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

## M2 — Honest evaluation

- Commands: `uv run game-discovery data split --config configs/portfolio.yaml`; then `uv run game-discovery evaluate --split validation --config configs/portfolio.yaml`.
- Frozen global whole-date split: cutoff A `2017-01-28`, cutoff B `2017-08-22`; 187,153 train, 40,180 validation and 40,201 test events. Each split and source sample has a SHA-256 in ignored `artifacts/manifests/split_manifest.json` (manifest SHA-256 `2ce5fc7db7f31ffcea7c06a827b46493aa7f9f738cf409c15ffdc70008eed841`).
- Validation evaluated 23,864 future-target users over the 7,266-item pre-cutoff catalog. Warm metrics cover 8,833 users; 9,358 targets are outside the catalog, 4,904 users have no reachable target and 12,821 have no training history.
- Baselines use the same users/catalog/exclusions. Warm NDCG@10: random `0.00002`, global popularity `0.04021`, recent-30-day `0.05146`, recent-90-day `0.04998`.
- Paired user-bootstrap (2,000, seed 1729) NDCG@10 differences vs global popularity: recent-30-day `+0.01125` (95% CI `+0.00835` to `+0.01405`); recent-90-day `+0.00977` (`+0.00701` to `+0.01257`).
- Results, reachability, exposure and reproduction details are in [EVALUATION.md](EVALUATION.md). Per-user contributions remain private in ignored `private/evaluation/validation_baselines.parquet`.
- `uv run pytest --basetemp tests/.pytest-tmp -q` — 8 passed; Ruff check and format check passed.
- Test outcomes have not been evaluated. The final-test command is gated until a selection record is frozen.

## Completed milestone history

### M3 — Learned ranking (completed locally)

- CPU implicit ALS grid: `uv run game-discovery train --config configs/portfolio.yaml`; eight configurations, 32/64 factors × 0.01/0.1 regularization × alpha 10/40, 20 iterations, seed 1729, one CPU/BLAS thread. Stored confidence is `1 + alpha`; the library multiplier is explicitly 1.0. Training artifacts and hashes are local/ignored.
- Integrated ALS training runtimes: 6.68–15.7 seconds per configuration; measured process peak RSS: 235–243 MiB. Best validation configuration was 32 factors, regularization 0.01, alpha 10. Warm NDCG@10 0.02855; paired difference vs global popularity -0.01166 (95% CI -0.01488 to -0.00844).
- Item-item cosine: sparse binary co-occurrence, cosine normalization, count shrinkage 20 and up to 200 deterministically selected neighbors per item. Integrated training took 2.86 seconds; matrix has 816,379 links. Validation warm NDCG@10 0.03555, paired difference vs global popularity -0.00466 (95% CI -0.00739 to -0.00192).
- Static metadata TF-IDF: title, genres and tags, fitted for the eligible catalog; 8,615 sparse features and 206,761 nonzeros; integrated construction took 0.64 seconds. Validation warm NDCG@10 0.01885. This is separately labeled because the metadata snapshot has no as-of timestamp.
- Rank-fusion blends use training-only recency/popularity and per-user unseen-catalog score ranks. A 10% content-rank + 90% recent-30-day-rank candidate scored NDCG@10 0.05317 vs 0.05146 for recent-30-day popularity; paired difference +0.00172 (95% CI -0.00172 to +0.00515). Catalog coverage rose 0.41% to 2.23%; tail exposure rose 0% to 0.44%. The interval includes zero, so this is not a statistically established improvement.
- Frozen validation choice and parameters are in [MODEL_SELECTION.md](MODEL_SELECTION.md) and [MODEL_SELECTION.json](MODEL_SELECTION.json). The final test partition remains unopened. Full metrics and model tradeoffs are in [EVALUATION.md](EVALUATION.md).
- Tests: `uv run pytest --basetemp tests/.pytest-tmp -q` — 13 passed. `uv run ruff check .` and `uv run ruff format --check .` passed.
- End-to-end `uv run game-discovery evaluate --split validation --config configs/portfolio.yaml` completed across baselines, all ALS settings, item-item, static metadata and hybrid weight sweep. The hybrid sweep was then refreshed after aligning both rank percentiles over each user's unseen catalog. It evaluates validation only; the test gate remains closed.

### M4 — Audit and export (completed)

Completed locally on 2026-10-25:

- Refit the frozen candidate on train + validation with `uv run game-discovery export --config configs/portfolio.yaml`. The export contains 8,637 catalog items and 9,620 TF-IDF features, uses the selection-recorded 10% content rank weight and 30-day popularity, and exports no user IDs, histories or user factors.
- Bundle: 3,838,684 bytes (about 3.66 MiB); uncompressed sparse features 1,960,320 bytes. Refit took 0.56 seconds. `uv run game-discovery verify-release --bundle models/release/selected_candidate` passed; fixed one- and three-seed profile rank parity passed. Loaded process RSS was 175.2 MiB.
- Before opening the test partition, `uv run pytest --basetemp tests/.pytest-tmp -q` passed 16 tests and Ruff checks passed. The tests include a synthetic frozen-test evaluator fixture.
- The one-time command `uv run game-discovery evaluate --split test --config configs/portfolio.yaml` completed in 255.96 seconds at 387.7 MiB peak RSS. The selected candidate reached warm NDCG@10 0.05152 versus 0.02769 for recent-30-day popularity; paired difference +0.02383 (95% CI +0.02106 to +0.02674, 10,556 warm users). Test results did not change the frozen candidate.
- Test reachability: 25,193 future-target users, 8,950 unreachable events, 4,827 users without reachable targets and 12,389 without history. Full aggregate metrics are in [EVALUATION.md](EVALUATION.md); per-user rows and detailed output remain ignored/private.
- M4 does not claim serving latency; only offline recommendation generation, bundle size and post-load RSS have been measured.
- After the final-test run, additional synthetic robustness cases for all-candidates-excluded, unknown-only seeds and corrupt catalog hashes passed (18 tests at that stage). These tests did not access or change final-test metrics or model selection.

### M5 — Product (completed locally)

- Added FastAPI routes for health/readiness, bounded catalog search, validated recommendations, model/data information, aggregate evaluation, local-only operational metrics and explicit feedback-disabled behavior. Readiness loads the hash-verified item-only champion bundle; the optional ALS item-only sidecar is labeled as a validation-era reference.
- Added a TypeScript/Vite front end with an accessible catalog picker (up to 20 seed games), optional genre filter, real popular/tail/sparse/cold-start/unknown examples, side-by-side same-input popularity/ALS/champion rankings, changed-rank indicators, raw score explanations, loading/error states and historical-data caveats. The evaluation view reads the saved aggregate JSON and displays the final-test result, paired interval, reachability cohort and coverage/exposure tradeoffs.
- Feedback remains visibly disabled because durable storage is not configured. `/v1/events` returns HTTP 503 and `persisted: false`; no event data is stored.
- Added a multi-stage local Docker image with pinned Node/Python base digests, locked frontend/Python dependencies, non-root runtime, readiness healthcheck, configurable `PORT`, one Uvicorn worker and single-thread numerical libraries. Raw data, private mappings, user histories and training dependencies are excluded from the image.
- `docker build -t game-discovery:local .` passed. The local image is 193,069,748 bytes (`sha256:d98ef78c41cdb726b9c96e1ab7ff3527fd9d28288c7eb34164a98ef02c8cde`); the in-container content-feature SHA-256 matches the local refit bundle. Container smoke verified healthy readiness, non-root UID 10001, actual catalog search/tail slice, saved final-test aggregate, seeded recommendation scores/explanations and disabled-feedback status. Browser inspection captured real model comparisons and the saved evaluation charts from the running app.
- Frontend: `npm ci`, `npm run typecheck`, `npm run build` and `npm audit --audit-level=high` passed in the Docker Node image; audit reported zero vulnerabilities. Python: 23 tests passed; Ruff check and format checks passed. Starlette emitted a deprecation warning for its TestClient/httpx integration.
- No cloud account/resources, external feedback persistence, request-capacity benchmark, deployment URL or cloud verification is claimed. M6 is next: durable-store decision, monitoring replay, promotion/rejection and rollback evidence.

## Next actions

### M6 — Lifecycle

- Select and verify a permitted private durable event store only after a protected-free-account preflight; otherwise retain the current read-only feedback-disabled mode.
- Implement separate real-demo, replay and synthetic-test event streams, bounded retention, signed impression attribution and truthful duplicate/storage-failure behavior.
- Add local drift replay evidence, candidate promotion/rejection and rollback tests without altering the frozen M3 selection or one-time M4 test result.
- Keep the data redistribution review open; do not publish data-derived artifacts until it is resolved.

## Evidence integrity

No cloud resource IDs, actual cloud costs, deployment URL or cloud verification are claimed. A live browser smoke was visually inspected against actual local model and evaluation outputs.
