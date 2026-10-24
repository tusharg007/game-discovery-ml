# Game Discovery

Game Discovery is a research and demo project for ranking historically observed Steam review interactions. Visitors will choose games they are interested in and see unseen games ranked with explanations grounded in model scores or catalog attributes.

The prediction target is a **future review interaction**. A review is evidence of interaction, not proof that its author liked the game. The system does not predict purchases, enjoyment, retention or playtime growth. Catalog metadata and any prices are historical snapshots, not a current storefront.

## Project status

M0 through M4 are complete locally: real data preparation, chronological evaluation, CPU model comparisons, a frozen validation selection, an item-only refit bundle and one final-test run. The static-metadata/content candidate beat recent popularity on the single final-test window, with the limitations in [EVALUATION.md](EVALUATION.md). The FastAPI/browser product and deployment are still in progress; no cloud verification is claimed. See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for commands, measured evidence and remaining gates.

## Planned local setup

The project targets Python 3.11 and `uv`; Docker Desktop is available for local container work:

```powershell
uv sync --extra train --extra dev
uv run game-discovery doctor
```

Training and dev dependencies are recorded in `uv.lock`. The local commands above are available in the implementation environment.

## Data and attribution

The intended source is the UCSD McAuley Lab Steam Video Game and Bundle Data. Consult [DATA_CARD.md](DATA_CARD.md) for provenance, limitations and the unresolved redistribution permission review. Raw reviews, usernames, profile URLs, full histories and private mappings must not be committed.

## Non-affiliation

This is an independent research/demo project and is not affiliated with or endorsed by Valve or Steam.
