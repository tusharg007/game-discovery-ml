# Cost Review

Updated: 2026-10-25 (Asia/Calcutta)

## Budget decision

- Target out-of-pocket spend: **0**.
- No cloud provider has been selected for provisioning. A read-only Azure CLI inspection found an enabled selected subscription, but no quota ID or spending limit was exposed and an Azure for Students offer could not be confirmed. Google Cloud and AWS CLIs are not installed, so their account eligibility is unverified.
- No paid API, GPU, domain, subscription, cloud resource, or billing upgrade has been requested or created.
- Local repository setup has no recorded external service cost. Actual device/runtime costs are not measured here.

## Deployment cost gate

The implementation plan defaults to Azure for Students and Azure Container Apps Consumption, subject to eligibility, credit balance/expiry, region capacity, resource quota, storage/logging/egress use and the subscription spending limit. The current Azure check does not pass the protected-free gate. No resources were provisioned and no billing setting changed. Sanitized local evidence is in ignored `artifacts/deployment/cost_preflight.json`. No cloud estimate is approval to spend.

Before any deployment resource mutation, populate `artifacts/deployment/cost_preflight.json` with the verified account offer, protection state, available credit/quota and shared usage, exact resource list, usage estimate, shutdown date, sources and a $0 acceptable out-of-pocket amount. If protected zero-out-of-pocket use cannot be established, cloud deployment remains incomplete.

## Current evidence

There is no deployed workload, bill, usage telemetry or measured request cost to report. The local container and offline tests do not establish cloud costs or permanent free usage.
