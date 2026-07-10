param(
  [Parameter(Mandatory=$true, Position=0)]
  [ValidateSet('list','add','remove','pull','pull-all','status')]
  [string]$Command,

  [Parameter(Position=1)]
  [string]$Domain,

  [Parameter(Position=2)]
  [string]$RepoUrl,

  [Parameter(Position=3)]
  [string]$Branch = "main",

  [switch]$KeepFiles
)

$ErrorActionPreference = 'Stop'

$MapPath = Join-Path $PSScriptRoot 'github_sources.json'
$WebsitesPath = Join-Path $PSScriptRoot 'websites'

function Ensure-Git {
  $null = Get-Command git -ErrorAction Stop
}

function Normalize-Domain([string]$d) {
  if ($null -eq $d) { return '' }
  return $d.Trim().ToLowerInvariant()
}

function Read-Map {
  if (-not (Test-Path $MapPath)) {
    return @{ domains = @{} }
  }
  $raw = Get-Content -Raw -Path $MapPath -Encoding UTF8
  if ([string]::IsNullOrWhiteSpace($raw)) {
    return @{ domains = @{} }
  }
  $parsed = $raw | ConvertFrom-Json
  $out = @{ domains = @{} }
  if ($null -ne $parsed -and $null -ne $parsed.domains) {
    foreach ($p in $parsed.domains.PSObject.Properties) {
      $out.domains[$p.Name] = @{
        repo = [string]$p.Value.repo
        branch = [string]$p.Value.branch
        updatedAt = [string]$p.Value.updatedAt
      }
    }
  }
  return $out
}

function Write-Map($obj) {
  $json = $obj | ConvertTo-Json -Depth 8
  Set-Content -Path $MapPath -Value $json -Encoding UTF8
}

function Ensure-DomainFolder([string]$domain) {
  $path = Join-Path $WebsitesPath $domain
  if (-not (Test-Path $path)) {
    New-Item -ItemType Directory -Path $path -Force | Out-Null
  }
  return $path
}

function Get-RepoInfo($map, [string]$domain) {
  if ($map.domains.ContainsKey($domain)) {
    return $map.domains[$domain]
  }
  return $null
}

function Git-CloneOrUpdate([string]$domain, [string]$repo, [string]$branch) {
  Ensure-Git
  $dest = Ensure-DomainFolder $domain
  $gitDir = Join-Path $dest '.git'

  if (-not (Test-Path $gitDir)) {
    if ((Get-ChildItem -Force -Path $dest | Measure-Object).Count -gt 0) {
      throw "Destination exists and is not a git repo: $dest"
    }
    & git clone --branch $branch --single-branch $repo $dest
    if ($LASTEXITCODE -ne 0) { throw "git clone failed for $domain" }
    return
  }

  & git -C $dest fetch origin
  if ($LASTEXITCODE -ne 0) { throw "git fetch failed for $domain" }

  & git -C $dest checkout $branch
  if ($LASTEXITCODE -ne 0) { throw "git checkout failed for $domain (branch: $branch)" }

  & git -C $dest pull --ff-only origin $branch
  if ($LASTEXITCODE -ne 0) { throw "git pull failed for $domain (branch: $branch)" }
}

switch ($Command) {
  'list' {
    $map = Read-Map
    $rows = @()
    foreach ($k in ($map.domains.Keys | Sort-Object)) {
      $v = $map.domains[$k]
      $rows += [PSCustomObject]@{
        Domain = $k
        Repo   = $v.repo
        Branch = $v.branch
        Path   = (Join-Path $WebsitesPath $k)
      }
    }
    if ($rows.Count -eq 0) {
      Write-Host "No GitHub sources configured."
    } else {
      $rows | Format-Table -Auto
    }
  }

  'add' {
    $d = Normalize-Domain $Domain
    if (-not $d) { throw 'Domain is required for add' }
    if (-not $RepoUrl) { throw 'RepoUrl is required for add' }
    if (-not $Branch) { $Branch = 'main' }

    Git-CloneOrUpdate -domain $d -repo $RepoUrl -branch $Branch

    $map = Read-Map
    $map.domains[$d] = @{
      repo = $RepoUrl
      branch = $Branch
      updatedAt = (Get-Date).ToString('s')
    }
    Write-Map $map
    Write-Host "Added/updated source for $d"
  }

  'pull' {
    $d = Normalize-Domain $Domain
    if (-not $d) { throw 'Domain is required for pull' }
    $map = Read-Map
    $info = Get-RepoInfo $map $d
    if ($null -eq $info) { throw "No source mapping found for $d" }
    Git-CloneOrUpdate -domain $d -repo $info.repo -branch $info.branch
    $map.domains[$d].updatedAt = (Get-Date).ToString('s')
    Write-Map $map
    Write-Host "Pulled $d"
  }

  'pull-all' {
    $map = Read-Map
    $keys = @($map.domains.Keys | Sort-Object)
    if ($keys.Count -eq 0) {
      Write-Host "No sources configured."
      break
    }
    foreach ($d in $keys) {
      $info = $map.domains[$d]
      Write-Host "Pulling $d ..."
      Git-CloneOrUpdate -domain $d -repo $info.repo -branch $info.branch
      $map.domains[$d].updatedAt = (Get-Date).ToString('s')
    }
    Write-Map $map
    Write-Host "Pull-all complete."
  }

  'remove' {
    $d = Normalize-Domain $Domain
    if (-not $d) { throw 'Domain is required for remove' }
    $map = Read-Map
    if (-not $map.domains.ContainsKey($d)) {
      Write-Host "No source mapping for $d"
      break
    }
    $map.domains.Remove($d) | Out-Null
    Write-Map $map
    if (-not $KeepFiles) {
      $path = Join-Path $WebsitesPath $d
      if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
      }
    }
    Write-Host "Removed source mapping for $d"
  }

  'status' {
    $map = Read-Map
    $rows = @()
    foreach ($d in ($map.domains.Keys | Sort-Object)) {
      $info = $map.domains[$d]
      $path = Join-Path $WebsitesPath $d
      $exists = Test-Path $path
      $head = ''
      if ($exists -and (Test-Path (Join-Path $path '.git'))) {
        try {
          $head = (& git -C $path rev-parse --short HEAD 2>$null).Trim()
        } catch {}
      }
      $rows += [PSCustomObject]@{
        Domain = $d
        Repo = $info.repo
        Branch = $info.branch
        Exists = $exists
        Head = $head
        UpdatedAt = $info.updatedAt
      }
    }
    if ($rows.Count -eq 0) {
      Write-Host "No sources configured."
    } else {
      $rows | Format-Table -Auto
    }
  }
}
