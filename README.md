# Game Discovery

Game Discovery is a research and demo project for ranking historically observed Steam review interactions. Visitors will choose games they are interested in and see unseen games ranked with explanations grounded in model scores or catalog attributes.

The prediction target is a **future review interaction**. A review is evidence of interaction, not proof that its author liked the game. The system does not predict purchases, enjoyment, retention or playtime growth. Catalog metadata and any prices are historical snapshots, not a current storefront.

## Project status

M0 through M5 are implemented locally: real data preparation, chronological evaluation, CPU model comparisons, a frozen validation selection, an item-only refit bundle, one final-test run and a containerized FastAPI/browser app. The static-metadata/content candidate beat recent popularity on the single final-test window, with the limitations in [EVALUATION.md](EVALUATION.md). Anonymous feedback is intentionally disabled because no durable store is configured. No cloud deployment is claimed. See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for evidence and remaining gates.

## Planned local setup

The project targets Python 3.11 and `uv`; Docker Desktop is available for local container work:

```powershell
uv sync --extra train --extra dev
uv run game-discovery doctor
```

Training and dev dependencies are recorded in `uv.lock`. The local commands above are available in the implementation environment.

## Data and attribution

The intended source is the UCSD McAuley Lab Steam Video Game and Bundle Data. Consult [DATA_CARD.md](DATA_CARD.md) for provenance, limitations and the unresolved redistribution permission review. Raw reviews, usernames, profile URLs, full histories and private mappings must not be committed.

## Run the local app

The Docker build compiles the TypeScript/Vite interface and installs the locked, inference-only Python dependencies. It expects the local release bundle, ALS comparison sidecar and saved test aggregate created by the M4 workflow; those artifacts remain ignored and are not included in Git.

```powershell
docker build -t game-discovery:local .
docker run --rm -p 127.0.0.1:8000:8000 game-discovery:local
```

Open `http://127.0.0.1:8000`. API documentation is available at `/docs`. The app exposes catalog search, same-profile champion/popularity/ALS comparison, explanations and charts read from the saved final-test JSON. `/v1/events` returns HTTP 503 with `persisted: false`; feedback is not stored. `/metrics` is local-only by default.

For a fresh checkout, create the local artifacts by following the commands and gates in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). Do not publish the derived bundle or evaluation files until the source data redistribution review in [DATA_CARD.md](DATA_CARD.md) is resolved.

## Non-affiliation

This is an independent research/demo project and is not affiliated with or endorsed by Valve or Steam.
