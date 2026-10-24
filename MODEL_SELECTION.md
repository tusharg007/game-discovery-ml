# Validation selection record

**Frozen:** 2026-10-25 (Asia/Calcutta)  
**Experiment:** future review-interaction ranking  
**Split manifest SHA-256:** `2ce5fc7db7f31ffcea7c06a827b46493aa7f9f738cf409c15ffdc70008eed841`  
**Validation window:** 2017-01-28 through 2017-08-21  
**Eligible catalog:** 7,266 items observed before cutoff A  
**Warm cohort:** 8,833 users

## Frozen candidate

- Candidate: `hybrid_recent30_content_w10`
- Ranking: 90% recent-30-day popularity rank percentile + 10% static-metadata TF-IDF profile rank percentile.
- Content features: title, genre and tag TF-IDF; 1–2 grams, minimum document frequency 2, maximum 50,000 features. The selected portfolio produced 8,615 features.
- NDCG@10: 0.05317.
- Paired difference vs recent-30-day popularity: +0.00172; 95% user-bootstrap CI [-0.00172, +0.00515], 2,000 resamples, seed 1729.
- Recent-30-day baseline NDCG@10: 0.05146.
- Relative point-estimate change: +3.3%; catalog coverage rises from 0.41% to 2.23%; tail exposure rises from 0% to 0.44%.
- The confidence interval includes zero. This selection is based on the highest observed NDCG point estimate among tested candidates and the exposure tradeoff, not evidence of a statistically established gain.
- Metadata is an untimestamped historical snapshot. The candidate is a separate static-metadata experiment and cannot establish historically available item features.

## Selection scope

The evaluated content rank weights were 10%, 15%, 20% and 25%, with the remainder assigned to recent-30-day popularity. The 10% setting had the highest validation NDCG among these settings. ALS and item-item references did not beat global popularity; ALS did not beat global popularity in any of its eight configurations. Content-only has NDCG@10 0.01885, coverage 69.98% and tail exposure 16.40%, showing the relevance/exposure tradeoff that motivated popularity mitigation.

This record was frozen before opening final-test results. Do not change it after viewing test metrics and reuse the same holdout. Test evaluation and train-plus-validation refitting remain M4 work.

Detailed aggregate metrics and runtime evidence: [EVALUATION.md](EVALUATION.md). User-level contributions and trained artifacts remain local and ignored.
