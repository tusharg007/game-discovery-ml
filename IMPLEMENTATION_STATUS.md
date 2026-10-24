# Implementation Status

Updated: 2026-10-25 (Asia/Calcutta)

Source plan: `E:\Game Discovery\GAME_DISCOVERY_IMPLEMENTATION_PLAN.md` (kept outside this separate repository).

## Current milestone: M7 — Render preparation (local checks passed; data publication gated)

M0–M5 have passed locally. M3 selection was frozen before the single M4 final-test run. Local M6 monitoring and promotion work is implemented. On 2026-10-25 the owner selected Render Free; its signed-in Hobby workspace has no card on file. The actual app passed the local Render resource-cap smoke. The owner confirmed no additional data-use permission was obtained, so real model/catalog assets remain local. Feedback is disabled and no cloud deployment is claimed.

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
- No cloud account/resources, external feedback persistence, request-capacity benchmark, deployment URL or cloud verification is claimed. M6 continues below.

### M6 — Lifecycle (local components implemented; external store gated)

- Added a common create-if-absent event-store protocol and a local directory adapter. Its hard-link create path is atomic across concurrent local writers; records use server receipt time and a 30-day local retention sweep. A restart test creates an event in one app process and verifies a duplicate against a new store/app instance.
- Added 30-minute HMAC-SHA256 impression tokens bound to model version and ranked item IDs, strict bounded feedback schemas, item attribution checks, secret-rotation/expiry tests and a best-effort 30-event-per-session-per-minute process limiter. Records do not include request IPs. The default serving app has no store or secret and continues to return HTTP 503 with `persisted: false`; LocalEventStore is explicitly marked `local_test_only`.
- Added `game-discovery monitor replay` for synthetic unknown-item, fallback, score and popularity shifts plus a stable control. Reports carry `event_stream: synthetic_test`, require 1,000 fixture samples and remain isolated from real-demo events. The saved popularity replay alerted on JSD `0.1742` against threshold `0.10`; the stable control emitted no alert.
- Added a 2% relative-NDCG promotion gate and a filesystem promotion ledger that retains rejected artifacts, checks artifact hashes and restores an earlier version on rollback. Synthetic tests cover regression rejection, accepted promotion, hash verification and rollback. A saved validation-only demo rejected the recent-30-day popularity candidate at -3.23% relative warm NDCG@10 against the frozen content/popularity candidate; active selection and release bundle stayed unchanged. The demo used validation outputs only and did not read the final-test report.
- Read-only Azure CLI preflight found the selected subscription enabled, with no quota ID or spending limit exposed and no student offer confirmed. `gcloud` and `aws` CLIs are absent, so alternate account eligibility is unverified. Sanitized evidence is in ignored `artifacts/deployment/cost_preflight.json`. No resource was provisioned, no billing setting changed and no paid service was enabled.
- Checks: 36 Python tests passed; Ruff check and format passed. The Docker Node image passed frontend typecheck, Vite build and npm audit (zero vulnerabilities). Synthetic replay and validation promotion CLI commands ran and saved ignored local reports. These results do not establish real-user drift, a production rate limit or external persistence.
- The cloud EventStore adapter and restart/duplicate checks against an eligible Azure/GCP/AWS object store remain gated on verifying a protected free account. Keep `/v1/events` disabled in the container until that account gate passes; do not configure an ephemeral container filesystem as durable storage.

## Next actions

### Selected Render route

- Render Hobby/no-card account eligibility is verified; use one Free web service after the data-use gate is resolved.
- Keep feedback disabled for the first Render launch. An external durable store with 30-day expiry and replacement/duplicate verification is a separate incomplete lifecycle capability.
- The local drift replay, promotion/rejection and rollback mechanisms are complete; do not use M4 test outcomes to retrain or change selection.
- Keep the data redistribution review open; do not publish data-derived artifacts until it is resolved.

## Evidence integrity

No cloud resource IDs, actual cloud costs, deployment URL or cloud verification are claimed. A live browser smoke was visually inspected against actual local model and evaluation outputs.

### M7 — Cloud deployment (templates only; account gate blocks provisioning)

- Added an Azure Bicep template for one Consumption Container Apps environment and one app, plus PowerShell and Bash preflight/plan/deploy/verify/rollback/destroy commands. The resource allowlist is project resource group + `Microsoft.App/managedEnvironments` + `Microsoft.App/containerApps`; no registry, storage, analytics workspace, VNet, Key Vault, or custom domain is created. The template uses scale-to-zero bounds (0–1), 0.25 vCPU/0.5 GiB, single revision, HTTPS ingress, no persistent log ingestion, digest-pinned images, and disabled feedback.
- Deployment and rollback require explicit mutation flags. Destroy requires a separate confirmation and validates project ownership tags and resource types before deleting project resources. Bash destroy is likewise scoped by tags and type. The plan mode is non-mutating and prints the allowlist; Azure `what-if` runs only if the named resource group already exists.
- No cloud mutation was run. The existing read-only Azure evidence does not confirm a protected student offer or spending limit; GCP/AWS eligibility is unverified. Template is locally authored, not cloud validated. Azure event storage is deliberately omitted while durable feedback remains gated. No HTTPS URL, external smoke, cloud load, rollback, or cloud cost evidence exists.
- The local deploy wrappers fail closed unless the cost-preflight JSON affirmatively records a protected free gate. The current ignored preflight fails that gate. This gate does not establish account eligibility by itself; evidence must be verified before use.

### M8 — Portfolio release (local docs and CI authored; final audit remains account/data gated)

- Added a model card, deployment status/procedure, local runbook, architecture diagram, fresh reproduction wrapper with stage resume, Git-tracked data/secret hygiene check, and CI for Python tests/Ruff, frontend typecheck/build/audit, and tracked-file hygiene. The image job builds a separately generated synthetic bundle and smoke-checks container readiness, UI HTML and disabled feedback; its fixture generator refuses to run without an explicit CI-only environment flag. CI does not pull the private dataset, release model, or final-test report.
- Expanded README with product purpose, live-link status, evaluation table, data counts, limits, reproduction instructions, monitoring and deployment status. No screenshots or derived figures were committed because redistribution permission is unresolved. The final-test report is left intact and was not rerun.
- Current verification for these changes: Python test suite 36 passed; Ruff check and format passed; PowerShell syntax parse passed. Frontend `npm ci`, typecheck, Vite build and audit were rerun in a disposable Node 22 container; audit reported zero vulnerabilities. The host npm shim points to a missing npm installation. The Azure CLI could not bootstrap Bicep, and no cloud `what-if` was run. Fresh-clone GitHub CI has not run.
- Remaining release work: resolve source/data publication permissions before publishing the real-data app, screenshots or derived figures; launch the selected Render Free service and verify actual HTTPS behavior; generate permitted figures and screenshots; finish the cloud evidence audit. The local functional resource smoke is not a cloud capacity benchmark. Durable cloud feedback remains optional and incomplete.

## Current blockers and next actions

1. Resolve the source dataset public-use question in plan section 3.3. The owner confirmed no additional permission has been obtained. Keep the real-data serving archive/image local until the applicable terms or permission are established.
2. Render is selected and signed in; Azure academic verification is no longer a launch dependency. Recheck the no-card Hobby account and select exactly one Free web service before deployment.
3. After data permission is resolved, publish the approved image, record its registry digest, create the Render service, and verify HTTPS, model identity, UI, bounded traffic, rollback and actual costs. Feedback remains disabled unless external durable storage is separately configured and tested.
4. Code-only fresh-checkout checks passed locally, including a locked Linux environment and synthetic container startup/API smoke. Hosted GitHub Actions remains disabled until its billing allowance is verified. Complete the cloud release evidence audit after the data-use gate is resolved. Never rerun the one-time final test or use it to promote/reselect a candidate.
- Template validation detail: PowerShell parser validation passed. The local Azure CLI could not bootstrap its Bicep compiler (it produced a locked zero-byte executable), so Bicep compilation and Azure `what-if` remain unverified. The host npm shim also points to a missing `npm-cli.js`; M6 frontend build/audit evidence remains valid, while the newly authored CI workflow has not run on GitHub.
- Rechecked the publisher lab dataset page on 2026-10-25: it still requests citation but provides no explicit redistribution license on the accessible page; the primary CSE dataset page timed out. Updated [DATA_CARD.md](DATA_CARD.md); derived publication rights remain unresolved.

### Render preparation — 2026-10-25

- Owner selected Render Free, replacing the Azure student-account route for the intended launch. Read-only dashboard evidence shows Hobby, no card on file, $0 accrued month-to-date charges, and available shared quotas. Sanitized account evidence is ignored in `artifacts/deployment/render_preflight.json`. No Render service has been created and no real-data image has been pushed.
- Added `deploy/render/prepare.py` and the Render deployment/rollback/shutdown procedure. The local packager verifies exact champion/ALS file hashes, privacy flags and saved-test split identity. It writes only the seven allowlisted serving assets into an ignored archive. The Blueprint generator requires a digest-pinned registry image and enforces exactly one Free image-backed web service. No database, disk, worker or paid plan is requested.
- Local release archive: 2,396,039 bytes; SHA-256 `ec21ef05a0c8f9780ed02e108e2c0575eca44214b3e79b8744c62483ed191193`. Manifest is ignored at `artifacts/deployment/render_release_manifest.json`. This is staging evidence, not publication approval.
- Built a Linux amd64 candidate tagged `game-discovery:render`, local image ID `sha256:be3916600fe931b5ec3de747d02973de3d13e1bee9598d50dd4fcabaebd24a57`. Docker disconnected during export, but the resulting image was inspected and successfully run after the engine recovered. The existing local app was also stopped by that engine event and has been restored. No registry digest or pushed image is claimed.
- The actual candidate passed 45 HTTP smoke requests under 0.1 CPU, a 512,000,000-byte memory cap, no swap and one worker. Cases cover popular/tail/sparse/cold/unknown profiles, 20-seed inputs, champion/popularity/ALS rankings, unique seed-excluding results, static assets/model readiness and disabled feedback (503, persisted false). Peak cgroup memory was 170,541,056 bytes, current 154,730,496 bytes, no OOM kill; measurements include the smoke client in the same cgroup. Saved ignored `render_local_smoke.json` and `render_memory_check.json`. This is not a Render cloud benchmark.
- 39 tests passed with intended one-thread numerical settings; Ruff passed. An initial full run hit a transient pandas import failure in an existing ALS test; the isolated ALS tests and then full suite passed. The Docker build passed frontend typecheck and Vite build. Container entrypoint now uses `exec` for signal delivery. The UI badge says historical research demo so it remains accurate on a hosted deployment.
- Public launch is blocked by the specific source-data gate in plan section 3.3 / `DATA_CARD.md`, not by Render account access. The owner stated no additional permission has been obtained. Continue code-only publication and clean-checkout validation; do not upload the real serving archive, model, catalog or real-data image until that gate is resolved.

### Code-only remote and fresh-checkout verification

- Created private repository `https://github.com/tusharg007/game-discovery-ml` and pushed source commit `3b62135`. Git history/current index privacy checks found no tracked raw data, user-level files, serving models or local reports beyond `.gitkeep` placeholders. The public-tree guard passed 86 tracked paths. No real release asset was transferred.
- GitHub Actions was disabled through repository settings before the first push because account-wide included Actions usage/billing has not been checked. No hosted workflow run is claimed. GitHub connector lacks repository creation, so the installed authenticated GitHub CLI was used.
- Cloned the private remote into a disposable checkout and installed the lockfile's 47 training/dev packages in Python 3.11.16 on Linux. The clean check identified the missing training-only `libgomp1` system prerequisite, which was installed in the disposable container and added explicitly to CI/runbook. Windows bind mounts report Python files executable, so source was copied to the container's native filesystem with the non-executable permissions recorded in Git before Ruff checks. All 39 tests, Ruff lint and format passed in that environment.
- Fresh-checkout locked frontend npm install, TypeScript check, Vite build and npm audit passed; zero npm advisories. A separate Docker build with explicitly synthetic CI catalog/model/evaluation fixtures completed successfully, producing local image `sha256:5d5d0ec6d282ea585949371414d3e9d9f8ba5b4ef7e32f96c8ec13c9bc5a9a5d`. Readiness, UI HTML, champion/popularity/ALS recommendations, and HTTP 503/non-persistence for disabled feedback passed. The temporary container was removed; the original localhost app remained ready.
- Source validation evidence is ignored at `artifacts/deployment/render_source_validation.json`. These checks use synthetic fixtures and do not replace the separate actual-model 512 MB resource smoke. No final-test evaluation was rerun.
- Added a shared 60-second deadline to the 45-request HTTP smoke and verified it against the existing localhost app; a separate ignored `render_local_deadline_smoke.json` records the successful check. No cloud request was made.
- Remaining launch blocker is the plan's source-data public-use gate. Render account access is available; the real-data image/serving assets remain local, and no Game Discovery Render service or public URL exists.
