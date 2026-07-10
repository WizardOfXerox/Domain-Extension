param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('php-xampp','node-express','wordpress-xampp','laravel','nextjs','vite-react','django','vue-vite')]
  [string]$Pack,

  [Parameter(Mandatory=$true)]
  [string]$Domain,

  [string]$Project = "app"
)

$ErrorActionPreference = 'Stop'

$Domain = $Domain.Trim().ToLowerInvariant()
if (-not $Domain) { throw "Domain is required." }

$siteRoot = Join-Path $PSScriptRoot "websites\$Domain"
New-Item -ItemType Directory -Path $siteRoot -Force | Out-Null
$repoRoot = Split-Path -Parent $PSScriptRoot
$packRoot = Join-Path $PSScriptRoot "packs\$Pack"
$siteTemplate = Join-Path $packRoot "site"
$backendTemplate = Join-Path $packRoot "backend"
$generatedRoot = Join-Path $repoRoot "examples\generated"
$generatedBackend = Join-Path $generatedRoot "$Domain-$Pack"

function Replace-TokensInFile([string]$path, [hashtable]$tokens) {
  if (-not (Test-Path $path)) { return }
  $ext = [System.IO.Path]::GetExtension($path).ToLowerInvariant()
  $textExt = @('.txt','.md','.json','.html','.htm','.js','.php','.env','.example','.sample','.conf')
  if ($textExt -notcontains $ext -and -not $path.ToLowerInvariant().EndsWith('dockerfile')) { return }
  try {
    $content = Get-Content -Raw -Path $path -Encoding UTF8
  } catch {
    return
  }
  foreach ($k in $tokens.Keys) {
    $content = $content.Replace($k, [string]$tokens[$k])
  }
  Set-Content -Path $path -Value $content -Encoding UTF8
}

function Replace-TokensRecursive([string]$root, [hashtable]$tokens) {
  if (-not (Test-Path $root)) { return }
  Get-ChildItem -Path $root -Recurse -File | ForEach-Object {
    Replace-TokensInFile -path $_.FullName -tokens $tokens
  }
}

$origin = ""
$btype = ""
$profile = $Pack
$health = "/"
$ws = ""
$notes = @()

switch ($Pack) {
  'php-xampp' {
    $origin = "http://127.0.0.1/$Project"
    $btype = "php"
    $notes += "Create project folder in XAMPP: C:\xampp\htdocs\$Project"
    $notes += "Start Apache in XAMPP."
  }
  'node-express' {
    $origin = "http://127.0.0.1:3000"
    $btype = "node"
    $ws = "/ws"
    $notes += "Start your Node/Express app on port 3000."
  }
  'wordpress-xampp' {
    $origin = "http://127.0.0.1/$Project"
    $btype = "php"
    $notes += "Install WordPress under C:\xampp\htdocs\$Project"
    $notes += "Start Apache + MySQL in XAMPP."
  }
  'laravel' {
    $origin = "http://127.0.0.1:8000"
    $btype = "php"
    $ws = "/app"
    $notes += "Run Laravel dev server: php artisan serve --host 127.0.0.1 --port 8000"
  }
  'nextjs' {
    $origin = "http://127.0.0.1:3000"
    $btype = "node"
    $notes += "Run Next.js dev server: npm run dev"
  }
  'vite-react' {
    $origin = "http://127.0.0.1:5173"
    $btype = "node"
    $notes += "Run Vite dev server: npm run dev"
  }
  'django' {
    $origin = "http://127.0.0.1:8000"
    $btype = "python"
    $notes += "Run Django server: python manage.py runserver 127.0.0.1:8000"
  }
  'vue-vite' {
    $origin = "http://127.0.0.1:5173"
    $btype = "node"
    $notes += "Run Vue-Vite dev server: npm run dev"
  }
}


$cfg = @{
  entry = "index.html"
  backend = @{
    origin = $origin
    type = $btype
    profile = $profile
    healthPath = $health
    wsPath = $ws
  }
}
$cfgJson = $cfg | ConvertTo-Json -Depth 8
Set-Content -Path (Join-Path $siteRoot "directory.json") -Value $cfgJson -Encoding UTF8

if (Test-Path $siteTemplate) {
  Copy-Item -Path (Join-Path $siteTemplate '*') -Destination $siteRoot -Recurse -Force
} else {
  $html = @"
<!doctype html>
<html>
  <head><meta charset="utf-8"><title>$Domain ($Pack)</title></head>
  <body>
    <h2>$Domain - Pack: $Pack</h2>
    <p>This domain is configured for backend origin: <code>$origin</code></p>
    <p>Use the extension popup/options to toggle local mode for real domains.</p>
  </body>
</html>
"@
  Set-Content -Path (Join-Path $siteRoot "index.html") -Value $html -Encoding ASCII
}

if (Test-Path $backendTemplate) {
  New-Item -ItemType Directory -Path $generatedRoot -Force | Out-Null
  New-Item -ItemType Directory -Path $generatedBackend -Force | Out-Null
  Copy-Item -Path (Join-Path $backendTemplate '*') -Destination $generatedBackend -Recurse -Force
}

$tokens = @{
  '__DOMAIN__' = $Domain
  '__PACK__' = $Pack
  '__ORIGIN__' = $origin
  '__PROJECT__' = $Project
}
Replace-TokensRecursive -root $siteRoot -tokens $tokens
if (Test-Path $generatedBackend) {
  Replace-TokensRecursive -root $generatedBackend -tokens $tokens
}

$readmeLines = @()
$readmeLines += "# Pack scaffold created"
$readmeLines += ""
$readmeLines += "Domain: $Domain"
$readmeLines += "Pack: $Pack"
$readmeLines += "Backend origin: $origin"
$readmeLines += ""
$readmeLines += "Next steps:"
foreach ($n in $notes) { $readmeLines += "- $n" }
$readmeLines += "- Template site files copied from: $siteTemplate"
if (Test-Path $generatedBackend) {
  $readmeLines += "- Backend starter generated at: $generatedBackend"
}
$readmeLines += "- Run start_all.bat"
$readmeLines += "- Open https://$Domain/"
Set-Content -Path (Join-Path $siteRoot "PACK-README.md") -Value $readmeLines -Encoding ASCII

Write-Host "Created pack '$Pack' for domain '$Domain' in $siteRoot"
