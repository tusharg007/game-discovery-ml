# Evaluation — future review-interaction ranking

Status: validation selection was frozen before the one-time final-test evaluation on 2026-10-25. The results below are served as a saved aggregate in the live Render application.

## Data and split

The current experiment uses the stable-hash portfolio sample: 100,134 selected users and 267,534 earliest user-item events. A global chronological split assigns every event on a boundary date to one window:

| Window | Rule | Events | Dates |
|---|---|---:|---|
| Train | Before cutoff A | 187,153 | 2010-10-16–2017-01-27 |
| Validation | Cutoff A through day before cutoff B | 40,180 | 2017-01-28–2017-08-21 |
| Test | Cutoff B onward | 40,201 | 2017-08-22–2018-01-05 |

The split manifest and each Parquet partition have SHA-256 hashes in local, ignored `artifacts/manifests/split_manifest.json`. Validation models fit only on events before cutoff A. The `test` command was gated until validation selection was frozen; the one-time final result is reported separately below.

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

## Learned and hybrid model results

The same frozen split, eligible catalog and warm cohort were used. ALS and item-item were compared with global popularity; the hybrid rank-fusion candidate was compared with the stronger recent-30-day baseline. Intervals use 2,000 paired user-bootstrap resamples with seed 1729.

| Model | Warm NDCG@10 | Catalog coverage@10 | Tail exposure@10 | Paired NDCG@10 difference (95% CI) |
|---|---:|---:|---:|---:|
| ALS, best validation config (32 factors, reg 0.01, alpha 10) | 0.02855 | 0.06152 | 0.000 | -0.01166 vs global [-0.01488, -0.00844] |
| Item-item cosine, shrinkage 20, 200 neighbors | 0.03555 | 0.59125 | 0.0565 | -0.00466 vs global [-0.00739, -0.00192] |
| Static metadata TF-IDF alone | 0.01885 | 0.69983 | 0.1640 | -0.02136 vs global [-0.02475, -0.01790] |
| Recent-30-day popularity | 0.05146 | 0.00413 | 0.000 | reference |
| **Selected validation candidate: 90% recent-30-day rank + 10% content rank** | **0.05317** | **0.02230** | **0.0044** | **+0.00172 vs recent-30-day [95% CI -0.00172 to +0.00515]** |

Rank fusion uses per-user unseen-catalog rank percentiles rather than blending raw scores. The 10% content weight was the highest-NDCG setting in the evaluated `{10%, 15%, 20%, 25%}` content sweep. It improves the validation point estimate by 3.3% and increases coverage and tail exposure. The interval includes zero, so the data do not establish that it beats recent popularity. It is frozen as the product candidate because it has the best observed NDCG point estimate while meeting the plan's 2% NDCG-loss guardrail and improving exposure; this is a validation choice, not a proven gain.

The unmitigated content reference has much higher tail exposure and catalog coverage but substantially lower NDCG. The recent-popularity blend controls that tradeoff. The underlying metadata has no as-of timestamp, so the selected candidate belongs to the separately labeled static-metadata experiment; it cannot establish historically available content features. ALS, item-item and content-only did not beat global popularity on this split. No test results informed the selection.

ALS training ran all eight planned configurations on CPU. In the integrated CLI run, runtimes were 6.68–15.7 seconds per configuration and peak process RSS was 235–243 MiB. Item-item cosine training took 2.86 seconds; the sparse 7,266-item matrix has 816,379 deterministically selected neighbor links. TF-IDF construction took 0.64 seconds with 8,615 features and 206,761 nonzeros. These are local training measurements; item-item and TF-IDF peak RSS was not captured. The integrated exact-catalog validation CLI completed successfully; scoring all eight ALS configurations was the longest step.

The committed [MODEL_SELECTION.md](MODEL_SELECTION.md) freezes the validation choice and constraints. Detailed reports and private per-user contributions are ignored local files under `artifacts/reports` and `private/evaluation`.

## Frozen final-test result

After freezing the selection record, the chosen candidate was refit on train plus validation and exported as an item-only bundle. The final test was then evaluated once, using only pre-cutoff-B history and the catalog observed before cutoff B.

| Model | Warm NDCG@10 | Warm Recall@10 | Warm HitRate@10 | All-target Recall@10 | Catalog coverage@10 | Tail exposure@10 |
|---|---:|---:|---:|---:|---:|---:|
| Recent-30-day popularity | 0.02769 | 0.05283 | 0.08374 | 0.04927 | 0.00255 | 0.0000 |
| **Frozen content/popularity candidate** | **0.05152** | **0.09912** | **0.14399** | **0.06758** | **0.02269** | **0.0119** |

The paired warm NDCG@10 difference is +0.02383 (95% CI +0.02106 to +0.02674; 10,556 warm users, 2,000 user-bootstrap resamples, seed 1729). This test result is reported as an untouched holdout result; it was not used to adjust the model or its weight. The test window has 25,193 future-target users; 8,950 target events are outside the pre-cutoff catalog, 4,827 users have no reachable target, and 12,389 users have no prior history. The catalog at cutoff B contains 8,637 items.

The selected candidate's test coverage is about 8.9 times the baseline's, with 1.19% of top-10 exposure going to the bottom 80% popularity tail versus zero for the baseline. Its test recommendation mean popularity and exposure concentration are also recorded in the local test report. Results are from one user-hash portfolio sample and one future window; the static metadata snapshot has no as-of timestamp, and review events do not prove user preference.

The release bundle is 3,838,684 bytes (about 3.66 MiB) on disk, below the 100 MiB goal. Its sparse feature payload is 1,960,320 bytes uncompressed. A local post-load process RSS measurement was 175.2 MiB, below the 400 MiB serving goal. The full final-test evaluation took 255.96 seconds and peaked at 387.7 MiB RSS; this is an offline evaluation measurement, not serving latency.

## Reproduction

```powershell
uv sync --extra train --extra dev
uv run game-discovery data split --config configs/portfolio.yaml
uv run game-discovery evaluate --split validation --config configs/portfolio.yaml
uv run game-discovery train --config configs/portfolio.yaml
uv run game-discovery export --config configs/portfolio.yaml
uv run game-discovery verify-release --bundle models/release/selected_candidate
uv run game-discovery evaluate --split test --config configs/portfolio.yaml
```

The baseline report and per-user bootstrap contributions are under ignored `artifacts/reports/validation_baselines.json` and `private/evaluation/validation_baselines.parquet`. Per-user values contain private pseudonymous user keys and must remain local. The owner-authorized demo exposes saved aggregate evaluation, item artifacts, and the historical catalog. [DATA_CARD.md](DATA_CARD.md) records source-terms uncertainty and decision scope. The [POC API capture](docs/evidence/live-api.json) reads that existing aggregate without rerunning the final test.
