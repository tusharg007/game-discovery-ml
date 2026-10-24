# Screenshot capture record

Captured against the public [Game Discovery app](https://game-discovery-ml.onrender.com) on **2026-10-25 (Asia/Calcutta)**. These are original browser screenshots of real catalog/model outputs. Scrolling and a section crop frame the relevant controls; no model values, text, or metrics were painted or generated.

The desktop overview is reused from the earlier verified deployment session that day; its exact capture timestamp was not preserved. The other images were captured for this walkthrough at the browser’s existing narrow viewport. Responsive columns therefore appear as separate screenshots. The evaluation screen displays an existing saved test aggregate, rather than a new evaluation run.

The popular-profile images use Black Squad (`550650`), Team Fortress 2 (`440`), and No Man's Sky (`275850`), no genre filter, and five requested results. The cold-start image uses no seeds. API responses in [live-api.json](../../evidence/live-api.json) were captured separately with the same documented inputs; request IDs and timings naturally differ.

Model: `portfolio-hybrid-content-popularity-v1`
Catalog/split: `2ce5fc7db7f31ffcea7c06a827b46493aa7f9f738cf409c15ffdc70008eed841`

| Capture | Contents | Dimensions |
|---|---|---|
| [00-desktop-overview.jpg](00-desktop-overview.jpg) | Verified desktop overview from earlier deployment session | 854 × 674 |
| [01-discover.jpg](01-discover.jpg) | Full Discover screen before selecting a profile | 560 × 1638 |
| [02-selected-profile.jpg](02-selected-profile.jpg) | Popular three-seed profile and five-result controls | 521 × 763 |
| [03-recent-popularity.jpg](03-recent-popularity.jpg) | Recent-popularity output for the popular profile | 561 × 651 |
| [04-als-reference.jpg](04-als-reference.jpg) | ALS validation-era reference for the popular profile | 561 × 651 |
| [05-selected-model.jpg](05-selected-model.jpg) | Selected fusion output for the popular profile | 561 × 651 |
| [06-evaluation.jpg](06-evaluation.jpg) | Saved final-test evaluation loaded by the app | 560 × 987 |
| [07-cold-start.jpg](07-cold-start.jpg) | Cold-start selected-model fallback banner | 561 × 651 |
| [08-attribution.jpg](08-attribution.jpg) | Public source-attribution page | 560 × 960 |

[capture.json](capture.json) preserves source URLs, saving timestamps, byte sizes, dimensions, and SHA-256 hashes. Hashes identify these files; they do not independently certify the model or dataset.

## SHA-256

| File | SHA-256 |
|---|---|
| 00-desktop-overview.jpg | `e78e5fa006bc40d112a28f0418ed4d8edec667ba3509aedc2102c050872ae4a5` |
| 01-discover.jpg | `3bb554a868890e40523977bc9fc71dbdc0a8c2c9851066492980f9c2c3b01bef` |
| 02-selected-profile.jpg | `b65a07c61c614d81a9c86cef3db1071f559f06ae393f44926642bc42c818ed47` |
| 03-recent-popularity.jpg | `cc6749d7745b52407d792314e3bf48579b0e5ebe36ea0704b2df4c5a924a7f31` |
| 04-als-reference.jpg | `81411b6b38a5412d4152f707e61570485c543dd2dd64abda57d69347777ae1e3` |
| 05-selected-model.jpg | `d5d957c5a22d3f415fda71b8097140b4a6acbc32a3c0c8dc52bdfc8993343313` |
| 06-evaluation.jpg | `4a728067b4f7f0d82c787503dff3ad400c59c076464fff38a218c5b21359ab03` |
| 07-cold-start.jpg | `738e10e0f37c11bc66583501042d18574bb3abb723509caaf01179d5880705cb` |
| 08-attribution.jpg | `6f14c3cbed12f8515972d686cf10020dc1849f3ac3a39c00651ab942a5743538` |

These assets show the UI and synthetic visitor requests. They contain no account dashboards, credentials, raw reviews, training users, or private visitor histories. See the [walkthrough](../../WALKTHROUGH.md) for reproduction and the [evaluation report](../../../EVALUATION.md) for the offline experiment.
