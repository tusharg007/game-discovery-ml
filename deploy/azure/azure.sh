#!/usr/bin/env bash
set -euo pipefail
action="${1:-}"; shift || true
usage() { echo 'Usage: azure.sh preflight|plan|deploy|verify|rollback|destroy [--apply] [--confirm-destroy]'; exit 2; }
[[ -n "$action" ]] || usage
apply=false; destroy=false
for arg in "$@"; do case "$arg" in --apply) apply=true;; --confirm-destroy) destroy=true;; *) usage;; esac; done
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
gate="artifacts/deployment/cost_preflight.json"
if [[ ! -f "$gate" ]]; then echo "Missing $gate; refusing cloud action." >&2; exit 1; fi
provider="$(jq -r '.provider // ""' "$gate")"
passed="$(jq -r '.protected_free_gate_passed // false' "$gate")"
if [[ "$action" != preflight && "$action" != plan ]]; then
  complete="$(jq -r '(.protected_offer_verified == true) and (.spending_limit_enabled == true) and (.paid_billing_enabled == false) and (.remaining_credit_reviewed == true) and (.shared_usage_reviewed == true) and (.region_verified == true) and (.resource_list_reviewed == true) and (.max_out_of_pocket_usd == 0) and ((.offer_expiry // "") != "") and ((.shutdown_date // "") != "") and ((.sources // []) | length > 0) and (.provisioning_performed == false)' "$gate")"
  [[ "$provider" == Azure && "$passed" == true && "$complete" == true ]] || { echo 'Protected zero-spend preflight fields are incomplete; refusing cloud mutation.' >&2; exit 1; }
fi
sub="${AZURE_SUBSCRIPTION_ID:-}"; suffix="${GAME_DISCOVERY_SUFFIX:-}"; location="${GAME_DISCOVERY_LOCATION:-}"
rg="game-discovery-${suffix}-rg"
if [[ "$action" == preflight ]]; then az account show --subscription "$sub" --output table; exit 0; fi
[[ -n "$sub" && -n "$suffix" ]] || { echo 'Set AZURE_SUBSCRIPTION_ID and GAME_DISCOVERY_SUFFIX.' >&2; exit 2; }
if [[ "$action" == plan || "$action" == deploy ]]; then
  image="${GAME_DISCOVERY_IMAGE:-}"; commit="$(git rev-parse HEAD)"; model="${GAME_DISCOVERY_MODEL_SHA256:-}"
  [[ "$image" =~ @sha256:[0-9a-f]{64}$ && "$model" =~ ^[0-9a-f]{64}$ && -n "$location" ]] || { echo 'Set digest-pinned GAME_DISCOVERY_IMAGE, GAME_DISCOVERY_MODEL_SHA256 and GAME_DISCOVERY_LOCATION.' >&2; exit 2; }
  params="$(mktemp)"; trap 'rm -f "$params"' EXIT
  jq -n --arg s "$suffix" --arg l "$location" --arg i "$image" --arg c "$commit" --arg m "$model" '{"$schema":"https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",contentVersion:"1.0.0.0",parameters:{nameSuffix:{value:$s},location:{value:$l},imageReference:{value:$i},gitCommit:{value:$c},modelSha256:{value:$m}}}' > "$params"
fi
case "$action" in
  plan) echo "Allowlist: resource group $rg; Microsoft.App/managedEnvironments; Microsoft.App/containerApps."; if [[ "$(az group exists --subscription "$sub" --name "$rg" -o tsv)" == true ]]; then az deployment group what-if --subscription "$sub" --resource-group "$rg" --template-file deploy/azure/main.bicep --parameters "@$params" --output table; else echo "Resource group $rg does not exist; no cloud what-if was run. The listed template allowlist changes nothing."; fi;;
  deploy) [[ "$apply" == true ]] || { echo 'Pass --apply only after reviewing plan.' >&2; exit 2; }; az group create --subscription "$sub" --name "$rg" --location "$location" --tags project=game-discovery owner=game-discovery-ml --output none; az deployment group create --subscription "$sub" --name game-discovery-release --resource-group "$rg" --template-file deploy/azure/main.bicep --parameters "@$params" --output table;;
  verify) app="game-discovery-${suffix}"; url="https://$(az containerapp show --subscription "$sub" --resource-group "$rg" --name "$app" --query properties.configuration.ingress.fqdn -o tsv)"; curl --fail --silent --show-error "$url/readyz";;
  rollback) [[ "$apply" == true ]] || { echo 'Pass --apply after reviewing the prior tested digest.' >&2; exit 2; }; [[ "${GAME_DISCOVERY_PREVIOUS_IMAGE:-}" =~ @sha256:[0-9a-f]{64}$ ]] || { echo 'Set digest-pinned GAME_DISCOVERY_PREVIOUS_IMAGE.' >&2; exit 2; }; az containerapp update --subscription "$sub" --resource-group "$rg" --name "game-discovery-${suffix}" --image "$GAME_DISCOVERY_PREVIOUS_IMAGE" --output table;;
  destroy)
    [[ "$destroy" == true ]] || { echo 'Pass --confirm-destroy after reviewing resources.' >&2; exit 2; }
    resources="$(az resource list --subscription "$sub" --resource-group "$rg" -o json)"
    jq -e 'all(.[]; .tags.project == "game-discovery" and .tags.owner == "game-discovery-ml" and (.type == "Microsoft.App/managedEnvironments" or .type == "Microsoft.App/containerApps"))' <<< "$resources" >/dev/null || { echo 'Unexpected resource or ownership tag; refusing destroy.' >&2; exit 1; }
    jq -r '.[] | [.type,.name] | @tsv' <<< "$resources"
    while IFS= read -r id; do [[ -z "$id" ]] || az resource delete --subscription "$sub" --ids "$id" --output none; done < <(jq -r '.[].id' <<< "$resources")
    group="$(az group show --subscription "$sub" --name "$rg" -o json)"
    jq -e '.tags.project == "game-discovery" and .tags.owner == "game-discovery-ml"' <<< "$group" >/dev/null || { echo 'Resource group ownership tags do not match; leaving group.' >&2; exit 1; }
    az group delete --subscription "$sub" --name "$rg" --yes --no-wait
    ;;
  *) usage;;
esac
