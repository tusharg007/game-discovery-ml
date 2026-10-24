# Cost Review

Updated: 2026-10-25 (Asia/Calcutta)

## Budget decision

- Target out-of-pocket spend: **0**.
- Render Free was selected by the owner on 2026-10-25. One Game Discovery Free web service is live in Singapore. Read-only post-launch dashboard inspection verified a Hobby workspace, no card on file, $0.00 accrued month-to-date charges, $0.00 projected October charges, and available shared free quotas. Earlier Azure inspection did not confirm a protected student offer; GCP/AWS eligibility is unverified.
- No paid API, GPU, domain, subscription, resource plan or billing upgrade was purchased.
- Local repository setup has no recorded external service cost. Actual device/runtime costs are not measured here.

## Deployment cost gate

### Selected route: Render Free

Use exactly one Free web service, one instance, existing image, no databases, disks, workers or paid upgrades. The post-launch workspace snapshot shows 53.75/750 free instance hours, 383 MB/5 GB bandwidth, 2/500 pipeline minutes and 17/25 services used; these totals include unrelated existing apps. Preserve the no-card state. Render documents suspension of Free services rather than bandwidth overage billing when no payment method is present, and disabling further builds when their allowance is exhausted. This is conditional on the actual account and service configuration; it is not a promise of unlimited hosting. [Render Free rules](https://render.com/docs/free)

Local resource smoke used 0.1 CPU, 512,000,000 bytes with no swap, and one worker. Peak cgroup memory was 170,541,056 bytes over 45 requests, including the smoke client. This is local evidence, not a measured Render bill or capacity benchmark. The owner has authorized the limited serving deployment described in `DATA_CARD.md`; no dataset license is inferred from that decision. The existing Docker Hub account is used for the serving image without purchasing a plan. See [Render deployment](deploy/render/README.md).

### Retained alternative: Azure

The implementation plan defaults to Azure for Students and Azure Container Apps Consumption, subject to eligibility, credit balance/expiry, region capacity, resource quota, storage/logging/egress use and the subscription spending limit. The current Azure check does not pass the protected-free gate. No resources were provisioned and no billing setting changed. Sanitized local evidence is in ignored `artifacts/deployment/cost_preflight.json`. No cloud estimate is approval to spend.

Before any deployment resource mutation, populate `artifacts/deployment/cost_preflight.json` with the verified account offer, protection state, available credit/quota and shared usage, exact resource list, usage estimate, shutdown date, sources and a $0 acceptable out-of-pocket amount. If protected zero-out-of-pocket use cannot be established, cloud deployment remains incomplete.

## Current evidence

The initial image-backed deploy succeeded in 40.1 seconds. The bounded HTTPS functional smoke passed 45 requests in 12.95 seconds. Render's Free dashboard reports memory/CPU telemetry as a paid feature; it was not enabled. The immediate billing snapshot is $0; usage/billing updates can lag and do not establish a measured per-request cost or permanent free usage. Image publication used the existing Docker Hub account and did not purchase a plan. The service may idle naturally; no keep-alive traffic is configured. Review continued hosting on 2026-11-25; suspend the named service if it is no longer needed. No automation or future shutdown is claimed.
