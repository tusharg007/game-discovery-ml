# Data sources and attribution

This independent, noncommercial research demo uses historical Steam review interactions and game metadata collected by the UC San Diego McAuley Lab. It is not affiliated with or endorsed by Valve, Steam, UC San Diego or the dataset authors.

- [Publisher dataset page](https://cseweb.ucsd.edu/~jmcauley/datasets.html#steam_data)
- [Accessible publisher dataset description and citations](https://mcauleylab.ucsd.edu/public_datasets/data/datasets.html)
- [Download mirror](https://huggingface.co/datasets/recommender-system/steam-review-and-bundle-dataset/tree/8e9c6b569122fb20668f5da3b0f3970a853fc5d8), pinned revision `8e9c6b569122fb20668f5da3b0f3970a853fc5d8`
- Source files used privately for research: `steam_reviews.json.gz` and `steam_games.json.gz`.

## Research references

1. Wang-Cheng Kang and Julian McAuley. *Self-Attentive Sequential Recommendation*. ICDM, 2018.
2. Mengting Wan and Julian McAuley. *Item Recommendation on Monotonic Behavior Chains*. RecSys, 2018.
3. Apurva Pathak, Kshitiz Gupta and Julian McAuley. *Generating and Personalizing Bundle Recommendations on Steam*. SIGIR, 2017.

The runtime contains item model features/factors, a historical game catalog, aggregate popularity counts and saved aggregate evaluation. It excludes raw reviews, usernames, profile URLs, user histories, user factors and private events. A review records interaction rather than verified liking. The catalog is historical, with no guaranteed metadata as-of date.

Attribution does not assign a license to the dataset. No explicit deployment prohibition was found on the accessible publisher page, and no permissive redistribution grant was established. The owner authorized this limited serving deployment on 2026-10-25. See [DATA_CARD.md](DATA_CARD.md) for provenance and the scope of that decision.
