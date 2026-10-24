# Evaluation — future review-interaction ranking

Status: M2 chronological evaluation and popularity baselines completed locally on 2026-10-24. The final test partition has not been evaluated.

## Data and split

The current experiment uses the stable-hash portfolio sample: 100,134 selected users and 267,534 earliest user-item events. A global chronological split assigns every event on a boundary date to one window:

| Window | Rule | Events | Dates |
|---|---|---:|---|
| Train | Before cutoff A | 187,153 | 2010-10-16–2017-01-27 |
| Validation | Cutoff A through day before cutoff B | 40,180 | 2017-01-28–2017-08-21 |
| Test | Cutoff B onward | 40,201 | 2017-08-22–2018-01-05 |

The split manifest and each Parquet partition have SHA-256 hashes in local, ignored `artifacts/manifests/split_manifest.json`. Validation models fit only on events before cutoff A. The `test` command is gated until validation selection is frozen; no test metrics have been opened.

## Catalog and users

The primary eligible catalog contains 7,266 items observed before cutoff A. Each user's training-history items are excluded from recommendations. The validation window contains 23,864 users with future targets and 40,180 target events. Of those targets, 9,358 are outside the eligible catalog; 4,904 users have no reachable future target, and 12,821 have no training history. All-target recall counts unreachable targets as misses. Warm-catalog metrics use the 8,833 users with prior history and at least one reachable target.

Relevance means a held-out review interaction. It does not mean the user liked or recommended the game. This experiment measures ranking of future review activity, not purchases, enjoyment or engagement uplift.

## Validation baseline results

Metrics are averaged per user. Warm-catalog metrics use only the named 8,833-user warm cohort; all-target Recall@10 averages across all future-target users and includes unreachable targets in each user's denominator. The 95% intervals below are paired user-bootstrap intervals over warm-catalog NDCG@10 differences versus global popularity, with 2,000 resamples and seed 1729.

| Model | Warm NDCG@10 | Warm Recall@10 | Warm HitRate@10 | All-target Recall@10 | Catalog coverage@10 | Tail exposure@10 | Paired NDCG@10 difference vs global (95% CI) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Uniform random | 0.00002 | 0.00001 | 0.00023 | 0.00005 | 0.00151 | 1.000 | -0.04019 [-0.04308, -0.03732] |
| Global popularity | 0.04021 | 0.06780 | 0.11321 | 0.07650 | 0.00674 | 0.000 | 0.00000 [0.00000, 0.00000] |
| Recent popularity, 30 days | **0.05146** | 0.09207 | 0.14253 | **0.10914** | 0.00413 | 0.000 | **+0.01125 [+0.00835, +0.01405]** |
| Recent popularity, 90 days | 0.04998 | **0.09220** | **0.14480** | 0.10526 | 0.00468 | 0.000 | +0.00977 [+0.00701, +0.01257] |

The 30-day recent-popularity baseline currently leads warm NDCG@10 and all-target Recall@10. The 90-day baseline has slightly higher warm Recall@10 and HitRate@10. Popularity baselines have very low catalog coverage and zero exposure to the bottom 80% item tail in their top-10 lists in this window. The random baseline is a metric sanity check, not a competitive model.

These are initial results from one portfolio sample and one validation window. They do not establish performance on full Steam data, a current storefront, or another future period. Historical metadata has no guaranteed as-of timestamp; metadata models will be reported as a separate static-metadata track.

## Reproduction

```powershell
uv sync --extra train --extra dev
uv run game-discovery data split --config configs/portfolio.yaml
uv run game-discovery evaluate --split validation --config configs/portfolio.yaml
```

The baseline report and per-user bootstrap contributions are under ignored `artifacts/reports/validation_baselines.json` and `private/evaluation/validation_baselines.parquet`. Per-user values contain private pseudonymous user keys and must remain local. Aggregate outputs remain local until data-derived publication permission is resolved.
