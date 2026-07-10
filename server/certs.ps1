param(
  [switch]$Install,
  [string]$DomainsFile = "$PSScriptRoot\domains.txt",
  [string]$CertOut = "$PSScriptRoot\certs\cert.pem",
  [string]$KeyOut  = "$PSScriptRoot\certs\key.pem"
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command mkcert -ErrorAction SilentlyContinue)) {
  Write-Error "mkcert not found in PATH. Install mkcert, then re-run."
}

if (-not (Test-Path $DomainsFile)) {
  Write-Error "Domains file not found: $DomainsFile"
}

$domains = Get-Content $DomainsFile |
  Where-Object { $_ -and (-not $_.Trim().StartsWith('#')) } |
  ForEach-Object { $_.Trim() } |
  Where-Object { $_ }

if ($domains.Count -eq 0) {
  Write-Error "No domains found in $DomainsFile"
}

$certDir = Split-Path -Parent $CertOut
if (-not (Test-Path $certDir)) { New-Item -ItemType Directory -Path $certDir -Force | Out-Null }

if ($Install) {
  mkcert -install | Write-Host
}

mkcert -cert-file $CertOut -key-file $KeyOut @domains | Write-Host

Write-Host "Wrote cert: $CertOut"
Write-Host "Wrote key : $KeyOut"
