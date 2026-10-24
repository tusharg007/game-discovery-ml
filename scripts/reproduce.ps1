param(
  [ValidateSet('all','data','split','train','validation','export')][string]$From = 'all',
  [string]$Config = 'configs/portfolio.yaml',
  [switch]$Download
)
$ErrorActionPreference = 'Stop'
function Invoke-Project([string[]]$Arguments) {
  & uv run game-discovery @Arguments
  if ($LASTEXITCODE -ne 0) { throw "Command failed: uv run game-discovery $($Arguments -join ' ')" }
}
$steps = @('data','split','train','validation','export')
$start = [Array]::IndexOf($steps, $From)
if ($From -eq 'all') { $start = 0 }
if ($start -lt 0) { throw 'Unknown resume stage.' }
if ($Download -and $start -eq 0) { Invoke-Project @('data','download','--config',$Config,'--source','auto') }
if ($start -le 0) { Invoke-Project @('data','prepare','--config',$Config) }
if ($start -le 1) { Invoke-Project @('data','split','--config',$Config) }
if ($start -le 2) { Invoke-Project @('train','--config',$Config) }
if ($start -le 3) { Invoke-Project @('evaluate','--split','validation','--config',$Config) }
if ($start -le 4) {
  Invoke-Project @('export','--config',$Config)
  Invoke-Project @('export-als-comparison')
  Invoke-Project @('verify-release')
}
Write-Output 'Local reproduction stages completed. The one-time final test is deliberately not part of this script.'
