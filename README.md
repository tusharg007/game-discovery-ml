# Game Discovery

Game Discovery is a research and demo project for ranking historically observed Steam review interactions. Visitors will choose games they are interested in and see unseen games ranked with explanations grounded in model scores or catalog attributes.

The prediction target is a **future review interaction**. A review is evidence of interaction, not proof that its author liked the game. The system does not predict purchases, enjoyment, retention or playtime growth. Catalog metadata and any prices are historical snapshots, not a current storefront.

## Project status

M0 bootstrap and M1 real-data preparation are complete locally. See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for the executed commands, measured data counts and remaining gates. Model training, evaluation, application and deployment have not been completed; no recommendation performance or deployment results are claimed.

## Planned local setup

The project targets Python 3.11 and `uv`:

```powershell
uv sync --extra train --extra dev
uv run game-discovery doctor
```

The runtime needed to create and validate `uv.lock` is not currently available in the implementation environment. Install Python 3.11 and `uv`, then regenerate the lock before treating the environment as reproducible.

## Data and attribution

The intended source is the UCSD McAuley Lab Steam Video Game and Bundle Data. Consult [DATA_CARD.md](DATA_CARD.md) for provenance, limitations and the unresolved redistribution permission review. Raw reviews, usernames, profile URLs, full histories and private mappings must not be committed.

## Non-affiliation

This is an independent research/demo project and is not affiliated with or endorsed by Valve or Steam.
