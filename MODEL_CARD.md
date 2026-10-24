# Model card: portfolio hybrid content and popularity

Updated 2026-10-25. Status: locally evaluated and served; no cloud deployment.

## Intended use

Rank historical Steam catalog items for a visitor who supplies up to 20 seed games. The target is a future review interaction, not purchase, enjoyment, satisfaction, or a verified positive rating. This is a research/demo model for discovery and comparison.

## Data and training

The private portfolio derives from timestamped Steam reviews and historical item metadata. The sample selected 100,134 username-proxy identities by stable hash and retained 267,534 events across 9,792 items. Duplicate user-item events retain the earliest timestamp. The global whole-date cutoffs are 2017-01-28 and 2017-08-22. Metadata is an untimestamped historical snapshot, so the content track can include catalog information unavailable at the historical prediction date. Dataset identity and redistribution limitations are recorded in [DATA_CARD.md](DATA_CARD.md).

## Method

The selected candidate fuses 10% static title/genre/tag TF-IDF rank with 90% 30-day popularity rank. It is refit on train plus validation and exports item features, item identifiers and popularity values only. It contains no user IDs, histories, user factors, feedback, or personal mappings. Recommendation ranking scores candidates over the available catalog and excludes seed and requested exclusion IDs.

## Evaluation

Selection was frozen before the one final-test run. On the warm catalog, final-test NDCG@10 was 0.05152 versus 0.02769 for the recent-30-day baseline. Paired difference was +0.02383 (95% user-bootstrap interval +0.02106 to +0.02674; 10,556 warm users). The warm metric excludes users without an eligible future target; 25,193 users had future targets overall. See [EVALUATION.md](EVALUATION.md) for reachability, other metrics and exposure tradeoffs. The test was evaluated exactly once and is not used for further tuning.

## Risks and limits

- A review is an interaction signal and does not establish that someone liked a game.
- Username is an identity proxy and may collide or change; it is not a verified person ID.
- Historical metadata is not time-aligned and cannot substantiate cold-item performance at a historical date.
- Exposure and ranking reflect severe interaction imbalance and popularity concentration; tail exposure is low.
- There are no randomized exposure logs, so feedback or rank differences do not establish causal engagement.
- The evaluation covers one sampled dataset and one temporal window; it does not establish current Steam behavior or generalization to all players.
- No serving load benchmark or cloud deployment has been completed.

## Serving and monitoring

The selected item-only bundle is hash verified at startup. The local API reports the model and catalog version, supports fallback cases explicitly, and exposes a local-only metrics endpoint. Feedback is disabled by default. Synthetic drift replay and validation-only promotion rejection/rollback are demonstrations, not live user monitoring or model updates.
