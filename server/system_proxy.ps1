param(
  [Parameter(Mandatory=$true, Position=0)]
  [ValidateSet('status','enable','disable','sync','add','remove','generate')]
  [string]$Command,

  [Parameter(Position=1)]
  [string]$Domain
)

$ErrorActionPreference = 'Stop'

$DomainsListPath = Join-Path $PSScriptRoot 'system_proxy_domains.txt'
$PacPath = Join-Path $PSScriptRoot 'system_proxy.pac'
$WebsitesPath = Join-Path $PSScriptRoot 'websites'
$ProxyHost = '127.0.0.1'
$ProxyPort = 9081
$FakeTlds = @('.fake','.test','.custom','.ssx')
$RegPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'

function Normalize-Domain([string]$d) {
  if ($null -eq $d) { return '' }
  return $d.Trim().ToLowerInvariant()
}

function Read-Domains {
  if (-not (Test-Path $DomainsListPath)) { return @() }
  $out = @()
  foreach ($raw in (Get-Content -Path $DomainsListPath -Encoding UTF8)) {
    $line = Normalize-Domain $raw
    if (-not $line) { continue }
    if ($line.StartsWith('#')) { continue }
    $out += $line
  }
  return ($out | Sort-Object -Unique)
}

function Write-Domains([string[]]$domains) {
  $lines = @('# Domains routed by system PAC (real domains only).')
  $lines += ($domains | Sort-Object -Unique)
  Set-Content -Path $DomainsListPath -Value $lines -Encoding UTF8
}

function Get-WebsiteDomains {
  if (-not (Test-Path $WebsitesPath)) { return @() }
  return Get-ChildItem -Path $WebsitesPath -Directory | ForEach-Object { $_.Name.ToLowerInvariant() } | Sort-Object -Unique
}

function Generate-Pac {
  $domains = Read-Domains
  $checksFake = @()
  foreach ($t in $FakeTlds) {
    $checksFake += "shExpMatch(host, '*$t')"
  }
  $checksReal = @()
  foreach ($d in $domains) {
    $checksReal += "host === '$d'"
  }

  $fakeExpr = if ($checksFake.Count -gt 0) { ($checksFake -join ' || ') } else { 'false' }
  $realExpr = if ($checksReal.Count -gt 0) { ($checksReal -join ' || ') } else { 'false' }

  $pac = @"
function FindProxyForURL(url, host) {
  host = (host || '').toLowerCase();
  if ($fakeExpr) return 'PROXY $ProxyHost`:$ProxyPort';
  if ($realExpr) return 'PROXY $ProxyHost`:$ProxyPort; DIRECT';
  return 'DIRECT';
}
"@
  Set-Content -Path $PacPath -Value $pac -Encoding ASCII
  Write-Host "Generated PAC: $PacPath"
}

function Get-PacUrl {
  $p = $PacPath -replace '\\','/'
  return "file:///$p"
}

function Enable-SystemPac {
  Generate-Pac
  $url = Get-PacUrl
  Set-ItemProperty -Path $RegPath -Name AutoConfigURL -Value $url
  Set-ItemProperty -Path $RegPath -Name ProxyEnable -Value 0
  Write-Host "Enabled system PAC: $url"
}

function Disable-SystemPac {
  Remove-ItemProperty -Path $RegPath -Name AutoConfigURL -ErrorAction SilentlyContinue
  Write-Host "Disabled system PAC (AutoConfigURL removed)."
}

switch ($Command) {
  'status' {
    $auto = (Get-ItemProperty -Path $RegPath -Name AutoConfigURL -ErrorAction SilentlyContinue).AutoConfigURL
    $pe = (Get-ItemProperty -Path $RegPath -Name ProxyEnable -ErrorAction SilentlyContinue).ProxyEnable
    Write-Host "AutoConfigURL: $auto"
    Write-Host "ProxyEnable : $pe"
    Write-Host "PAC exists   : $(Test-Path $PacPath)"
    Write-Host "Domains file : $DomainsListPath"
    Write-Host "Domains count: $((Read-Domains).Count)"
  }
  'sync' {
    $domains = Get-WebsiteDomains
    # Keep fake TLDs in PAC rules (not here); only add real/fake concrete domains found.
    Write-Domains $domains
    Write-Host "Synced system proxy domains from websites: $($domains.Count)"
    Generate-Pac
  }
  'add' {
    $d = Normalize-Domain $Domain
    if (-not $d) { throw 'Domain required for add' }
    $domains = Read-Domains
    if ($domains -notcontains $d) { $domains += $d }
    Write-Domains $domains
    Generate-Pac
    Write-Host "Added: $d"
  }
  'remove' {
    $d = Normalize-Domain $Domain
    if (-not $d) { throw 'Domain required for remove' }
    $domains = Read-Domains | Where-Object { $_ -ne $d }
    Write-Domains $domains
    Generate-Pac
    Write-Host "Removed: $d"
  }
  'generate' {
    Generate-Pac
  }
  'enable' {
    Enable-SystemPac
  }
  'disable' {
    Disable-SystemPac
  }
}
