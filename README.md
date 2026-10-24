# Game Discovery

Game Discovery is a research demo that helps visitors find historically related Steam games from a few titles they already know. It searches a historical catalog, ranks unseen games, explains recommendations, and compares popularity, collaborative filtering, and the selected hybrid on the same input.

**Live demo:** none. The application has been run locally in Docker and checked in a browser; no cloud URL has been verified. Last local browser check: 2026-10-25.

## Screenshots

Recommendation and model-comparison screenshots are not published. The source dataset’s redistribution permission remains unresolved, so the repository keeps derived application evidence local. The local interface has been inspected against real model outputs; evaluation numbers and behavior are described here and in [EVALUATION.md](EVALUATION.md).

## Data and target

The source is the UCSD McAuley Lab Steam Video Game and Bundle Data, retrieved from the pinned Hugging Face mirror after the publisher host failed normal TLS verification. The complete compressed review file was 1,338,063,248 bytes and yielded 7,793,069 valid timestamped events. A stable user-hash portfolio sample retained 267,534 events for 100,134 username-proxy identities across 9,792 items. A review means someone interacted enough to write a review; it does not show that they liked the game. The model predicts a future review interaction, not purchase, enjoyment, retention, or playtime growth. Catalog metadata is historical and has no guaranteed as-of date. Provenance and the open reuse question are in [DATA_CARD.md](DATA_CARD.md).

## Offline results

The global whole-date windows use cutoffs 2017-01-28 and 2017-08-22. The warm catalog contains items observed before each prediction cutoff, and every compared model shares the same users and candidate set. The final test was run once after validation selection was frozen.

| Candidate | Warm NDCG@10 | Comparison |
|---|---:|---|
| Global popularity | 0.04021 validation | Validation baseline |
| Recent 30-day popularity | 0.05146 validation; 0.02769 test | Validation baseline and test comparator |
| Selected content + recent-popularity rank fusion | 0.05317 validation; 0.05152 test | 10% static content rank + 90% recent-30-day rank |

On the final test, selected-candidate difference versus recent popularity was +0.02383 (95% paired user-bootstrap interval +0.02106 to +0.02674, 10,556 warm users). There were 25,193 future-target users overall; unreachable items and users without history are counted in the all-target view. This is one historical window, with a static-metadata caveat. Evaluation reports include coverage, tail exposure and cohort limitations. **Serving latency is not measured.** There is no live link or cloud capacity result.

## Architecture and model

See [ARCHITECTURE.md](ARCHITECTURE.md). Training and exact candidate ranking run on CPU. For this compact eligible catalog, exact scoring keeps candidate construction explicit and avoids the operational and indexing cost of an approximate nearest-neighbor service. The selected release bundle contains item-side catalog features and popularity data, with no user histories or factors. The method and intended-use limits are in [MODEL_CARD.md](MODEL_CARD.md).

The data pipeline streams bounded records, validates and deduplicates earliest user-item interactions, and fits each comparison using only the permitted historical window. Interaction imbalance means popularity dominates exposure; the content component increases tail exposure modestly, but does not remove popularity bias. A review is not a verified like, and the historical metadata snapshot is not time aligned.

## Model lifecycle and deployment

Local synthetic drift replay, a validation-only candidate rejection, and synthetic promotion/rollback checks are saved in ignored reports. These are demonstrations, not real-user monitoring. Feedback is visibly disabled in the app because there is no durable event store. The local rate limiter is process scoped and not a billing cap.

Render Free is the selected hosting route. The actual app passed a local 45-request smoke at 0.1 CPU under a 512 MB memory cap; measured peak memory was about 171 MB, including the smoke client. The signed-in Render account is Hobby with no card on file. An allowlisted release packager and image-backed Blueprint generator are ready, but the real-data model/catalog remain local until the data-use gate is resolved. There is no live Render URL or cloud benchmark. Azure templates remain an unused alternative. See [DEPLOYMENT.md](DEPLOYMENT.md), [COSTS.md](COSTS.md), and [RUNBOOK.md](RUNBOOK.md) for status and shutdown procedure.

## Reproduce locally

Requires Python 3.11, `uv`, Node 22 for frontend work, Docker Desktop for the app image, and sufficient disk for the source data. The full local data and model artifacts are intentionally ignored by Git.

```powershell
uv sync --extra train --extra dev
uv run game-discovery doctor
./scripts/reproduce.ps1 -Download
```

The resume stages are `-From data|split|train|validation|export`. The script intentionally does not rerun the one-time final test. Review the provenance and data-use gate before acquiring or publishing derived artifacts. Build the local app after the M4 bundle, ALS comparison and saved aggregate are present:

```powershell
docker build -t game-discovery:local .
docker run --rm -p 127.0.0.1:8000:8000 game-discovery:local
```

CI runs Python tests and lint/format checks, frontend typecheck/build/audit, a Docker startup/API smoke against a separately generated synthetic bundle, and tracked-file privacy hygiene. It does not download the full dataset or run the frozen final test. See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for exact commands, hashes and milestone evidence.

## Non-affiliation

This is an independent research/demo project and is not affiliated with or endorsed by Valve or Steam.
