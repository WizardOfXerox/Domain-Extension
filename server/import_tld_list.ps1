param(
  # Download from: https://tld-list.com/free-downloads
  [string]$InputJson = "C:\\Users\\XIA\\Downloads\\tld-list-details.json",
  [string]$OutFile = "$PSScriptRoot\\tlds.txt"
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $InputJson)) {
  throw "Input JSON not found: $InputJson"
}

# The file format is a JSON object where top-level keys are TLDs without dots.
# Example: { "com": { ... }, "net": { ... } }
$data = Get-Content -Raw -Path $InputJson | ConvertFrom-Json

if ($null -eq $data -or $data.PSObject.Properties.Count -eq 0) {
  throw "No TLD entries found in $InputJson"
}

$tlds = @()
foreach ($p in $data.PSObject.Properties) {
  $name = [string]$p.Name
  if (-not $name) { continue }
  $tlds += ('.' + $name.ToLowerInvariant())
}

$tlds = $tlds | Sort-Object -Unique

# Write UTF-8 (no BOM) so other tools don't choke.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($OutFile, $tlds, $utf8NoBom)

Write-Host "Wrote $($tlds.Count) TLDs to $OutFile"