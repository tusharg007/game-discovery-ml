param(
  [Parameter(Mandatory=$true)][ValidateSet('preflight','plan','deploy','verify','rollback','destroy')][string]$Action,
  [string]$SubscriptionId,
  [string]$Location,
  [string]$Suffix,
  [string]$ImageReference,
  [string]$GitCommit,
  [string]$ModelSha256,
  [string]$PreviousImageReference,
  [string]$CostPreflight = 'artifacts/deployment/cost_preflight.json',
  [switch]$Apply,
  [switch]$ConfirmDestroy
)
$ErrorActionPreference = 'Stop'
$project = 'game-discovery'
$resourceGroup = "$project-$Suffix-rg"
$template = 'deploy/azure/main.bicep'
$parameters = 'deploy/azure/parameters.local.json'

function Require-Account {
  $account = az account show --output json | ConvertFrom-Json
  if ($LASTEXITCODE -ne 0) { throw 'Azure CLI is not signed in. Run az login, then rerun preflight.' }
  if ($SubscriptionId -and $account.id -ne $SubscriptionId) { throw 'Active subscription does not match SubscriptionId.' }
  if ($account.state -ne 'Enabled') { throw 'Subscription is not enabled.' }
  return $account
}
function Require-CostGate {
  if (!(Test-Path $CostPreflight)) { throw "Missing cost preflight: $CostPreflight" }
  $gate = Get-Content $CostPreflight -Raw | ConvertFrom-Json
  $complete = $gate.protected_offer_verified -eq $true -and
    $gate.spending_limit_enabled -eq $true -and
    $gate.paid_billing_enabled -eq $false -and
    $gate.remaining_credit_reviewed -eq $true -and
    $gate.shared_usage_reviewed -eq $true -and
    $gate.region_verified -eq $true -and
    $gate.resource_list_reviewed -eq $true -and
    $gate.max_out_of_pocket_usd -eq 0 -and
    -not [string]::IsNullOrWhiteSpace($gate.offer_expiry) -and
    -not [string]::IsNullOrWhiteSpace($gate.shutdown_date) -and
    $gate.sources.Count -gt 0
  if ($gate.provider -ne 'Azure' -or $gate.protected_free_gate_passed -ne $true -or $gate.provisioning_performed -ne $false -or !$complete) {
    throw 'Cost preflight is not a verified protected-free Azure gate. No mutation is allowed.'
  }
}
function Require-Parameters {
  if (!$Suffix -or !$Location -or !$ImageReference -or !$GitCommit -or !$ModelSha256) { throw 'Supply Suffix, Location, ImageReference, GitCommit and ModelSha256.' }
  if ($ImageReference -notmatch '@sha256:[0-9a-f]{64}$') { throw 'ImageReference must be pinned by sha256 digest.' }
  if ($ModelSha256 -notmatch '^[0-9a-f]{64}$') { throw 'ModelSha256 must be a 64-character SHA-256.' }
}
function Write-Parameters([string]$Image) {
  $json = @{ '$schema'='https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'; contentVersion='1.0.0.0'; parameters=@{
    nameSuffix=@{value=$Suffix}; location=@{value=$Location}; imageReference=@{value=$Image}; gitCommit=@{value=$GitCommit}; modelSha256=@{value=$ModelSha256}
  }} | ConvertTo-Json -Depth 8
  Set-Content -LiteralPath $parameters -Value $json -Encoding utf8
}
function Get-ProjectResources {
  $resources = az resource list --resource-group $resourceGroup --output json | ConvertFrom-Json
  if ($LASTEXITCODE -ne 0) { throw "Could not list resources in $resourceGroup" }
  foreach ($r in $resources) {
    $tags = $r.tags
    if ($tags.project -ne $project -or $tags.owner -ne 'game-discovery-ml') { throw "Resource $($r.id) lacks expected ownership tags. Refusing action." }
    if ($r.type -notin @('Microsoft.App/managedEnvironments','Microsoft.App/containerApps')) { throw "Unexpected resource type $($r.type). Refusing action." }
  }
  return $resources
}

switch ($Action) {
  'preflight' {
    $a = Require-Account
    Write-Output "Subscription: $($a.id) | state: $($a.state) | tenant: redacted"
    if (!(Test-Path $CostPreflight)) { throw 'Cost preflight evidence is missing.' }
    $g = Get-Content $CostPreflight -Raw | ConvertFrom-Json
    Write-Output "Protected zero-spend gate: $($g.protected_free_gate_passed)"
    if ($g.protected_free_gate_passed -ne $true) { throw 'Preflight failed closed; no cloud mutation is available.' }
  }
  'plan' {
    Require-Parameters; $null = Require-Account; Write-Parameters $ImageReference
    Write-Output "Allowlisted resources: resource group $resourceGroup; Microsoft.App/managedEnvironments; Microsoft.App/containerApps. No storage/logging workspace/registry."
    if (az group exists --name $resourceGroup --output tsv) {
      az deployment group what-if --resource-group $resourceGroup --template-file $template --parameters "@$parameters" --output table
      if ($LASTEXITCODE -ne 0) { throw 'Azure what-if failed.' }
    } else {
      Write-Output "Resource group $resourceGroup does not exist; no cloud what-if was run. This plan is the exact template resource allowlist and changes nothing."
    }
  }
  'deploy' {
    if (!$Apply) { throw 'Deployment requires -Apply after reviewing plan output.' }
    Require-Parameters; Require-CostGate; $null = Require-Account; Write-Parameters $ImageReference
    az group create --name $resourceGroup --location $Location --tags project=$project owner=game-discovery-ml --output none
    if ($LASTEXITCODE -ne 0) { throw 'Resource group creation failed.' }
    az deployment group create --name game-discovery-release --resource-group $resourceGroup --template-file $template --parameters "@$parameters" --output table
    if ($LASTEXITCODE -ne 0) { throw 'Container Apps deployment failed.' }
  }
  'verify' {
    $null = Require-Account
    $app = az containerapp show --name "$project-$Suffix" --resource-group $resourceGroup --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Could not read Container App.' }
    $url = "https://$($app.properties.configuration.ingress.fqdn)"
    $health = Invoke-RestMethod -Uri "$url/readyz" -TimeoutSec 60
    if ($health.status -ne 'ready') { throw 'Readiness response did not report ready.' }
    Write-Output "Verified HTTPS readiness: $url/readyz | model: $($health.model_version)"
  }
  'rollback' {
    if (!$Apply) { throw 'Rollback requires -Apply after reviewing the target image.' }
    if (!$PreviousImageReference -or $PreviousImageReference -notmatch '@sha256:[0-9a-f]{64}$') { throw 'Supply a prior tested digest in PreviousImageReference.' }
    Require-CostGate; $null = Require-Account
    az containerapp update --name "$project-$Suffix" --resource-group $resourceGroup --image $PreviousImageReference --output table
    if ($LASTEXITCODE -ne 0) { throw 'Rollback update failed.' }
  }
  'destroy' {
    if (!$ConfirmDestroy) { throw 'Destroy requires -ConfirmDestroy.' }
    $null = Require-Account; $rs = Get-ProjectResources
    Write-Output "Resources to delete in ${resourceGroup}:"; $rs | ForEach-Object { Write-Output "  $($_.type) $($_.name)" }
    foreach ($r in $rs) {
      az resource delete --ids $r.id --output none
      if ($LASTEXITCODE -ne 0) { throw "Delete failed for $($r.id)" }
    }
    $group = az group show --name $resourceGroup --output json | ConvertFrom-Json
    if ($group.tags.project -ne $project -or $group.tags.owner -ne 'game-discovery-ml') { throw 'Resource group ownership tags do not match; leaving group.' }
    az group delete --name $resourceGroup --yes --no-wait
  }
}
