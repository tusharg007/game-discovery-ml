# Deployment status and procedure

## Current state

**Live:** [https://game-discovery-ml.onrender.com](https://game-discovery-ml.onrender.com). On 2026-10-25, one image-backed Render Free service was deployed in Singapore. The signed-in workspace is Hobby, with no card on file and available shared free usage. The initial deployment succeeded in 40.1 seconds. All 45 bounded HTTPS checks passed in 12.95 seconds, with maximum concurrency five. Browser checks verified the comparison, saved aggregate evaluation and attribution pages. Feedback remains disabled. [Release identity](deploy/render/release.json) records the source commit and immutable registry digest.

The final image also passed a local 45-request smoke at 0.1 CPU and a 512,000,000-byte memory limit with no swap; peak cgroup memory was 127,758,336 bytes with the smoke client outside the container. Earlier measurement including the smoke client was 170,541,056 bytes. Render Free's dashboard gates actual memory/CPU telemetry behind a paid compute plan; no upgrade was made. The functional smoke is not a capacity benchmark.

After separate owner approval, a same-image replacement deployment passed 45 HTTPS checks in 11.47 seconds. Rollback to the first successful deployment then passed 45 checks in 11.74 seconds, with unchanged model/catalog identity and disabled feedback. This tests recovery between Render deployment revisions using the same image; it does not demonstrate switching between different trained models. The service remains on the chosen digest.

See [the Render deployment procedure](deploy/render/README.md). Serving assets are hash-verified and staged in an ignored local archive. On 2026-10-25 the owner explicitly authorized publication of the item-only inference bundle and historical catalog while keeping raw data and user records private. [DATA_CARD.md](DATA_CARD.md) records this change to the earlier publication hold and the unresolved source-terms uncertainty. The generated Blueprint requires an actual pushed registry image digest; no local image ID is presented as a registry digest. Feedback remains disabled.

## Azure template (retained alternative)

The earlier Azure preflight did not confirm an Azure for Students offer or spending limit; GCP and AWS eligibility remains unknown. Azure scripts continue to fail closed until their own account gate passes. Do not upgrade billing or remove a spending limit to make them pass.

The Azure template in `deploy/azure/main.bicep` creates one Consumption Container Apps environment and one app. It does not create storage, a registry, a workspace, a network, or a paid domain. Event persistence is not wired to Azure and feedback remains disabled. The app uses 0.25 vCPU / 0.5 GiB, zero minimum and one maximum replica, HTTPS ingress, single revision, and no persistent log ingestion. The selected image must be pinned by digest.

## Preflight and plan (non-mutating)

Complete `artifacts/deployment/cost_preflight.json` from account-visible evidence before any mutation. It must verify offer type/expiry, spending protection, remaining credit, shared usage, permissions, supported region, resource inventory, storage/logging/egress assumptions, shutdown date, and a $0 out-of-pocket ceiling. Do not copy account identifiers or tokens into public artifacts.

PowerShell:

```powershell
./deploy/azure/azure.ps1 -Action preflight
./deploy/azure/azure.ps1 -Action plan -SubscriptionId <id> -Location <region> -Suffix <unique-suffix> -ImageReference <image@sha256:digest> -GitCommit <sha> -ModelSha256 <sha256>
```

Bash requires Azure CLI, `jq`, and these environment variables: `AZURE_SUBSCRIPTION_ID`, `GAME_DISCOVERY_SUFFIX`, `GAME_DISCOVERY_LOCATION`, `GAME_DISCOVERY_IMAGE`, and `GAME_DISCOVERY_MODEL_SHA256`. Generated local parameters are ignored by Git.

```bash
./deploy/azure/azure.sh preflight
./deploy/azure/azure.sh plan
```

Review the exact proposed resource types and Azure `what-if` output. If the named resource group does not exist, the script prints the precise template allowlist without creating it; Azure cannot produce a group-scoped what-if for a not-yet-created group without changing deployment scope. No plan has been executed against Azure because account access was unavailable to the current process.

## Mutating commands

Only after cost preflight passes, the image/model hashes are verified, and the plan has been reviewed:

```powershell
./deploy/azure/azure.ps1 -Action deploy -Apply ...
./deploy/azure/azure.ps1 -Action verify -SubscriptionId <id> -Suffix <suffix>
./deploy/azure/azure.ps1 -Action rollback -Apply -PreviousImageReference <prior-image@sha256:digest> ...
./deploy/azure/azure.ps1 -Action destroy -ConfirmDestroy -SubscriptionId <id> -Suffix <suffix>
```

The deployment script requires the verified cost gate and digest-pinned image. Destruction prints and validates only tagged Container Apps resources under the project-named group and requires the explicit destructive flag. Inspect every resource before confirming. Bash has equivalent plan/deploy/verify/rollback flows and tag/type-scoped destruction.

After deployment, verify HTTPS readiness, model hash/version, UI/API behavior, and (if later configured) durable event behavior across replacement. Measure actual cold starts, latency, errors, memory, resource configuration, credit usage and shutdown behavior. Cloud load testing must remain under 200 requests and 60 seconds. Roll back to a previously tested image digest and then restore the chosen revision. Destroy resources after the exercise and verify no retained billable resources.

## Other providers

GCP Cloud Run and AWS Lambda are not implemented or verified. Do not represent their designs in the plan as working deployment scripts. Cloud deployment remains incomplete until one eligible provider is externally verified.
