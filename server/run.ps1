param(
  [int]$ControlPort = 9080,
  [int]$HttpsPort = 8443,
  [int]$ProxyPort = 9081
)

$ErrorActionPreference='Stop'

Write-Host "Starting control plane on http://127.0.0.1:$ControlPort"
Write-Host "Starting HTTPS vhost server on https://0.0.0.0:$HttpsPort"
Write-Host "Starting PAC proxy on http://127.0.0.1:$ProxyPort (CONNECT tunnels to local HTTPS)"

# Bind to IPv6 so ::1 hosts entries work. Many systems also accept IPv4 via dual-stack.
$env:XAI_PROXY_PORT = "$ProxyPort"
python "$PSScriptRoot\app.py" --control-port $ControlPort --https-host :: --https-port $HttpsPort
