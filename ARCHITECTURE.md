# Architecture

```mermaid
flowchart LR
  R[Historical review records] --> P[Bounded parsing and deduplication]
  M[Historical catalog metadata] --> P
  P --> S[Date-frozen train / validation / test]
  S --> T[CPU baselines, ALS, item-item, content, hybrid]
  T --> V[Validation selection frozen before test]
  V --> E[One-time final test and aggregate report]
  V --> B[Item-only release bundle]
  B --> A[FastAPI inference API]
  A --> W[TypeScript browser app]
  A -. feedback off by default .-> F[Optional signed event store; cloud adapter gated]
  D[Synthetic isolated drift replay] --> G[Promotion gate and local rollback ledger]
```

All raw and user-level data stay local. The serving bundle contains item-side data only. Historical metadata is not guaranteed to be time-aligned. The Dockerized FastAPI service and TypeScript app are deployed together on one Render Free service; Azure templates remain an unused alternative. See the [POC walkthrough](docs/WALKTHROUGH.md) and [release record](deploy/render/release.json). Feedback is disabled; drift and promotion exercises are local synthetic demonstrations.
