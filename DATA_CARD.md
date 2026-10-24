# Data Card — UCSD Steam review interactions

## Status

Local research processing is complete for the full files and a stable-hash portfolio sample. Redistribution and public-deployment permission for source data and derived artifacts remain unresolved. Raw files, per-user data, identity mappings and model inputs stay local and ignored by Git; do not publish them until the applicable permission is resolved.

## Intended source and provenance

UCSD McAuley Lab, *Steam Video Game and Bundle Data*, full review interactions and item metadata:

- Dataset description and citation guidance: https://cse.ucsd.edu/~jmcauley/datasets.html#steam_data
- Publisher directory: https://mcauleylab.ucsd.edu/public_datasets/data/steam/
- Files used: `steam_reviews.json.gz` and `steam_games.json.gz`.
- The publisher host failed normal HTTPS verification with an expired certificate. The downloader did not disable certificate checks. It used the plan-pinned mirror at revision `8e9c6b569122fb20668f5da3b0f3970a853fc5d8`.
- Both local SHA-256 values matched the pinned repository's API-provided LFS SHA-256 values. This verifies the downloaded bytes against that mirror revision; byte identity with the publisher files has not been independently established.
- Exact requested URLs, redirect destinations (with temporary query tokens removed), bytes, local hashes, upstream digests, revision, download time and the publisher TLS failure are recorded in the ignored local `artifacts/manifests/source_manifest.json`.

The publisher page asks users to cite the appropriate research reference. Rechecked on 2026-10-25: the accessible lab dataset page still requests citation and does not provide an explicit license or grant of redistribution rights; the primary CSE page timed out during this check. That does not establish permission to republish source files or derived artifacts. Resolve the applicable terms before public release; do not assign the software license to this dataset.

## Processed snapshot

Measured from the downloaded files on 2026-10-24:

- Review source: 7,793,069 valid timestamped review-interaction rows.
- Earliest user-item event table after deduplication: 6,889,728 rows, 2,567,538 dataset identity-proxy users and 15,474 items.
- Item metadata file: 32,133 rows, 2 missing item IDs, and 32,132 unique metadata IDs; the observed interaction catalog has metadata for every item.
- Portfolio: stable SHA-256 threshold selected 100,134 users (3.8948% derived from the observed unique-user count), retaining all 267,534 valid events for selected users across 9,792 items.
- Quality: 903,341 later duplicate user-item events removed; no duplicate source rows, invalid dates, parser rejects, conflicting metadata IDs or orphan interactions were observed in this run.
- Event dates span 2010-10-15 through 2018-01-05. These records describe historical review activity.
- Interaction matrix sparsity is 99.9827%. In this pre-split snapshot, the top 1% of items account for 36.35% of review interactions and the top 10% for 82.85%; the bottom 80% by interaction count account for 7.70%.

Counts describe this pinned mirror version and local processing run. The portfolio is user-hash sampled, not a random row sample; all events for selected users are retained, so event volume reflects user activity.

## Measurement and identity limits

The primary label is a timestamped review interaction. It is not a verified positive recommendation. `username` is an identity proxy, not a stable verified account identifier; name collisions or changes may occur. Usernames are converted using a locally held random HMAC key, and raw review text and usernames are omitted from processed tables. Hashing pseudonymizes identities; it does not anonymize them. These tables and the private mapping key remain local.

## Known limits

- Historical snapshot; not a current game catalog, price feed or storefront.
- Review activity measures interaction, not liking, purchases, retention, enjoyment or playtime.
- Missing interactions are unknown, not verified dislikes.
- Historical metadata has no guaranteed as-of timestamp.
- No claim is made that the mirror is byte-identical to publisher files.
- Historical item tags have no guaranteed as-of timestamp; later content experiments must be labeled as a static-metadata track.

## Required processing evidence

Created locally: `source_manifest.json`, `data_quality.json`, `dataset_stats.json`, `preparation_manifest.json` and `data_profile.html`. The temporal split manifest is still required before model evaluation. These current artifacts remain ignored/local until publication permissions are resolved.
