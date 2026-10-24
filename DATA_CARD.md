# Data Card — planned Steam interaction source

## Status

Source-data use review is in progress. No data files have been downloaded or processed in this repository. Do not publish raw files or derived serving artifacts until redistribution and public-deployment permissions for the chosen source are resolved.

## Intended source and provenance

UCSD McAuley Lab, *Steam Video Game and Bundle Data*, full review interactions and item metadata:

- Dataset description and citation guidance: https://cse.ucsd.edu/~jmcauley/datasets.html#steam_data
- Publisher directory: https://mcauleylab.ucsd.edu/public_datasets/data/steam/
- Intended files: `steam_reviews.json.gz` and `steam_games.json.gz`.
- A pinned community mirror is specified in the supplied implementation plan and may be used only if publisher access fails, with provenance and hashes recorded.

The publisher page asks users to cite the appropriate research reference. The current page reviewed on 2026-10-24 does not provide an explicit license or grant of redistribution rights. That does not establish permission to republish source files or derived artifacts. Resolve the applicable terms before public release; do not assign the software license to this dataset.

## Intended measurement

The primary label is a timestamped review interaction. It is not a verified positive recommendation. `username` is an identity proxy, not a stable verified account identifier. The planned workflow uses private opaque mappings and excludes identities, review text and user factors from serving artifacts.

## Known limits

- Historical snapshot; not a current game catalog, price feed or storefront.
- Review activity measures interaction, not liking, purchases, retention, enjoyment or playtime.
- Missing interactions are unknown, not verified dislikes.
- Historical metadata has no guaranteed as-of timestamp.
- Publisher counts and file sizes will not be copied into reports; actual downloaded file hashes and processed counts must be measured.

## Required processing evidence

Before modeling, create `source_manifest.json`, `data_quality.json`, `dataset_stats.json`, `data_profile.html`, and a versioned split manifest. Record source URL/revision, redirect destination, bytes, SHA-256, download time, upstream digest comparison where available, dropped-record counts and sample-selection details.
