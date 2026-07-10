param(
  [Parameter(Mandatory=$true, Position=0)]
  [ValidateSet('sync','add','remove','disable')]
  [string]$Command,

  [Parameter(Position=1)]
  [string]$Domain
)

$ErrorActionPreference = 'Stop'

$HostsPath = "$env:WINDIR\System32\drivers\etc\hosts"
$StartTag = '# Domain Extension start'
$EndTag   = '# Domain Extension end'

function Get-DomainsFromFolders {
  $base = Join-Path $PSScriptRoot 'websites'
  if (-not (Test-Path $base)) { return @() }
  Get-ChildItem -Path $base -Directory | ForEach-Object { $_.Name }
}

function Read-Hosts {
  if (-not (Test-Path $HostsPath)) { throw "Hosts file not found: $HostsPath" }
  Get-Content -Path $HostsPath -Encoding ASCII
}

function Write-Hosts($lines) {
  # Hosts can be temporarily locked by AV/editors. Retry for a few seconds.
  $max = 25
  for ($i = 1; $i -le $max; $i++) {
    $tmp = "$HostsPath.domainext.tmp"
    try {
      Set-Content -Path $tmp -Value $lines -Encoding ASCII -Force
      Move-Item -Path $tmp -Destination $HostsPath -Force
      return
    } catch [System.IO.IOException] {
      Remove-Item -Path $tmp -Force -ErrorAction SilentlyContinue | Out-Null
      if ($i -eq $max) { throw }
      Start-Sleep -Milliseconds (150 * $i)
      continue
    }
  }
}

function Get-BlockDomains($existingLines) {
  $domains = @()
  $inBlock = $false
  foreach ($l in $existingLines) {
    if ($l -eq $StartTag) { $inBlock = $true; continue }
    if ($l -eq $EndTag) { $inBlock = $false; continue }
    if ($inBlock) {
      $parts = ($l -split '\s+')
      if ($parts.Count -ge 2 -and ($parts[0] -eq '127.0.0.1' -or $parts[0] -eq '::1')) {
        $domains += $parts[1]
      }
    }
  }
  return ($domains | Sort-Object -Unique)
}

function Upsert-Block($existingLines, $domains) {
  $pre = @()
  $inBlock = $false
  foreach ($l in $existingLines) {
    if ($l -eq $StartTag) { $inBlock = $true; continue }
    if ($l -eq $EndTag) { $inBlock = $false; continue }
    if (-not $inBlock) { $pre += $l }
  }

  $block = @($StartTag)
  foreach ($d in ($domains | Sort-Object -Unique)) {
    $block += "127.0.0.1 $d"
    $block += "::1 $d"
  }
  $block += $EndTag

  $out = @()
  $out += $pre
  if ($out.Count -gt 0 -and $out[-1] -ne '') { $out += '' }
  $out += $block
  return $out
}

function Remove-Block($existingLines) {
  $out = @()
  $inBlock = $false
  foreach ($l in $existingLines) {
    if ($l -eq $StartTag) { $inBlock = $true; continue }
    if ($l -eq $EndTag) { $inBlock = $false; continue }
    if (-not $inBlock) { $out += $l }
  }
  return $out
}


$lines = Read-Hosts

switch ($Command) {
  'sync' {
    $domains = Get-DomainsFromFolders
    $newLines = Upsert-Block $lines $domains
    Write-Hosts $newLines
    Write-Host "Synced hosts block with $($domains.Count) domain(s)."
  }
  'add' {
    if (-not $Domain) { throw 'Domain required for add' }
    $current = Get-BlockDomains $lines
    $current += $Domain
    $newLines = Upsert-Block $lines $current
    Write-Hosts $newLines
    Write-Host "Added: $Domain"
  }
  'remove' {
    if (-not $Domain) { throw 'Domain required for remove' }
    $current = Get-BlockDomains $lines | Where-Object { $_ -ne $Domain }
    $newLines = Upsert-Block $lines $current
    Write-Hosts $newLines
    Write-Host "Removed: $Domain"
  }
  'disable' {
    $newLines = Remove-Block $lines
    Write-Hosts $newLines
    Write-Host "Disabled Domain Extension hosts block."
  }

}
