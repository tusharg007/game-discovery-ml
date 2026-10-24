# Cost Review

Updated: 2026-10-24 (Asia/Calcutta)

## Budget decision

- Target out-of-pocket spend: **0**.
- No cloud provider has been selected for provisioning and no account has been inspected or changed.
- No paid API, GPU, domain, subscription, cloud resource, or billing upgrade has been requested or created.
- Local repository setup has no recorded external service cost. Actual device/runtime costs are not measured here.

## Deployment cost gate

The implementation plan defaults to Azure for Students and Azure Container Apps Consumption, subject to eligibility, credit balance/expiry, region capacity, resource quota, storage/logging/egress use and the subscription spending limit. These account facts have not been verified. No cloud estimate is approval to spend.

Before any deployment resource mutation, populate `artifacts/deployment/cost_preflight.json` with the verified account offer, protection state, available credit/quota and shared usage, exact resource list, usage estimate, shutdown date, sources and a $0 acceptable out-of-pocket amount. If protected zero-out-of-pocket use cannot be established, cloud deployment remains incomplete.

## Current evidence

This is a bootstrap review only. There is no deployed workload, bill, usage telemetry or measured request cost to report.
