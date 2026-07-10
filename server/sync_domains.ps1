param(
  [switch]$UpdateCert
)

$ErrorActionPreference = "Stop"

$DomainsPath = Join-Path $PSScriptRoot "domains.txt"
$WebsitesPath = Join-Path $PSScriptRoot "websites"
$Defaults = @("*.fake","*.test","*.custom","*.ssx")

function Get-WebsiteDomains {
  if (-not (Test-Path $WebsitesPath)) { return @() }
  return Get-ChildItem -Path $WebsitesPath -Directory | ForEach-Object { $_.Name.ToLowerInvariant() } | Sort-Object -Unique
}

function Read-DomainsText {
  if (-not (Test-Path $DomainsPath)) { return @() }
  return Get-Content -Path $DomainsPath -Encoding UTF8
}

function Write-DomainsText([string[]]$lines) {
  Set-Content -Path $DomainsPath -Value $lines -Encoding UTF8
}

function Parse-ExistingDomains([string[]]$lines) {
  $set = New-Object 'System.Collections.Generic.HashSet[string]'
  foreach ($raw in $lines) {
    $line = ""
    if ($null -ne $raw) { $line = $raw.Trim() }
    if (-not $line) { continue }
    if ($line.StartsWith("#")) { continue }
    [void]$set.Add($line.ToLowerInvariant())
  }
  return $set
}

$lines = Read-DomainsText
$existing = Parse-ExistingDomains $lines
$websiteDomains = Get-WebsiteDomains

$toAdd = New-Object System.Collections.Generic.List[string]
foreach ($d in $websiteDomains) {
  if (-not $existing.Contains($d)) { $toAdd.Add($d) }
}
foreach ($d in $Defaults) {
  if (-not $existing.Contains($d)) { $toAdd.Add($d) }
}

$changed = $false
if ($toAdd.Count -gt 0) {
  $changed = $true
  if ($lines.Count -gt 0 -and $lines[-1].Trim() -ne "") { $lines += "" }
  $lines += "# Auto-added by sync_domains.ps1"
  foreach ($d in ($toAdd | Sort-Object -Unique)) {
    $lines += $d
  }
  Write-DomainsText $lines
  Write-Host "Added $($toAdd.Count) domain(s)/wildcard(s) to domains.txt"
} else {
  Write-Host "domains.txt already contains all website domains + default wildcards."
}

if ($UpdateCert -and $changed) {
  Write-Host "domains.txt changed. Regenerating cert..."
  & (Join-Path $PSScriptRoot "certs.ps1")
}
