# Cost Review

Updated: 2026-10-25 (Asia/Calcutta)

## Budget decision

- Target out-of-pocket spend: **0**.
- Render Free was selected by the owner on 2026-10-25. Read-only dashboard inspection verified a Hobby workspace, no card on file, $0.00 accrued month-to-date charges, and available shared free quotas. No Game Discovery service has been provisioned. Earlier Azure inspection did not confirm a protected student offer; GCP/AWS eligibility is unverified.
- No paid API, GPU, domain, subscription, cloud resource, or billing upgrade has been requested or created.
- Local repository setup has no recorded external service cost. Actual device/runtime costs are not measured here.

## Deployment cost gate

### Selected route: Render Free

Use exactly one Free web service, one instance, existing image, no databases, disks, workers or paid upgrades. The current workspace snapshot shows 53.7/750 free instance hours, 383 MB/5 GB bandwidth, and 2/500 pipeline minutes used; all allowances are shared with other services and must be rechecked at launch. Preserve the no-card state. Render documents suspension of Free services rather than bandwidth overage billing when no payment method is present, and disabling further builds when their allowance is exhausted. This is conditional on the actual account and service configuration; it is not a promise of unlimited hosting. [Render Free rules](https://render.com/docs/free)

Local resource smoke used 0.1 CPU, 512,000,000 bytes with no swap, and one worker. Peak cgroup memory was 170,541,056 bytes over 45 requests, including the smoke client. This is local evidence, not a measured Render bill or capacity benchmark. The owner has authorized the limited serving deployment described in `DATA_CARD.md`; no dataset license is inferred from that decision. The existing Docker Hub account is used for the serving image without purchasing a plan. See [Render deployment](deploy/render/README.md).

### Retained alternative: Azure

The implementation plan defaults to Azure for Students and Azure Container Apps Consumption, subject to eligibility, credit balance/expiry, region capacity, resource quota, storage/logging/egress use and the subscription spending limit. The current Azure check does not pass the protected-free gate. No resources were provisioned and no billing setting changed. Sanitized local evidence is in ignored `artifacts/deployment/cost_preflight.json`. No cloud estimate is approval to spend.

Before any deployment resource mutation, populate `artifacts/deployment/cost_preflight.json` with the verified account offer, protection state, available credit/quota and shared usage, exact resource list, usage estimate, shutdown date, sources and a $0 acceptable out-of-pocket amount. If protected zero-out-of-pocket use cannot be established, cloud deployment remains incomplete.

## Current evidence

There is no deployed workload, bill, usage telemetry or measured request cost to report. The local container and offline tests do not establish cloud costs or permanent free usage.
