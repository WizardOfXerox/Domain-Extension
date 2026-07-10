# Domain Extension - Documentation (v3.0)

## What this project does

This project lets you keep URLs like `https://www.google.com/...` or `https://example.fake/...` while loading content from your local machine.

Current architecture (v3.0):
- Browser extension PAC routing -> local proxy `127.0.0.1:9081`
- Control plane API -> `http://127.0.0.1:9080/__xai/*` (FastAPI + Uvicorn)
- Local HTTPS vhost server -> `https://[::]:443` (FastAPI + Uvicorn)
- Async upstream fetching via `httpx` (replaces curl.exe subprocesses)
- Built-in LAN DNS server -> `udp://0.0.0.0:53` (intercepts fake TLDs, relays others)

Routing behavior:
- Fake TLDs (`.fake`, `.test`, `.custom`, `.ssx`) route local automatically.
- Real domains route local only when enabled in extension state (`localDomains`).
- Wildcard patterns (e.g., `*.google.com`) match subdomains.
- LAN DNS: Devices using the host PC as their DNS server get fake TLDs resolved to the PC's LAN IP automatically.

## Architecture (Detailed)

### Request flow (real domain, Local OFF)
1. Browser asks PAC logic how to route.
{{ ... }}
2. Local HTTPS vhost handles request by Host header.
3. If local site exists, local content is served.
4. If not, fallback behavior applies as configured.

### Request flow (LAN device, DNS mode)
1. Device DNS is set to the host PC's LAN IP (e.g., `192.168.1.50`).
2. Device queries `dashboard.fake` -> built-in DNS returns `192.168.1.50`.
3. Device queries `google.com` -> DNS relays to `1.1.1.1` and returns the real IP.
4. Device connects to `https://dashboard.fake:443` which hits the HTTPS vhost on the PC.

### Components and responsibility
- `sw.js`: PAC state manager with wildcard/subdomain support (Chrome).
- `firefox/background.js`: Proxy request handler with wildcard support (Firefox).
- `popup.js`: quick per-tab controls, quick-add button, and recovery actions.
- `options.js`: advanced control surface (allowlist, backend config, metrics, probes, health, **live dashboard**).
- `server/app.py`: FastAPI control plane + HTTPS vhost + CONNECT proxy + LAN DNS + async upstream/backends.
- `manage.py`: Cross-platform CLI (Windows/macOS/Linux) replacing PowerShell scripts.
- `server/github_sync.ps1`: repo sync into `server/websites/<domain>`.

### New v3.0 Features
- **Path-based routing**: `directory.json` `routes` array with `mock`, `proxy`, and `static` actions.
- **API mocking**: Return canned responses for matched path patterns.
- **Header injection**: Add/remove request headers, set response headers.
- **Latency simulation**: `latencyMs` field in `directory.json`.
- **Developer watermark**: Configurable banner injected into HTML responses.
- **Styled directory explorer**: Automatic file listing when entry file is missing.
- **Live request dashboard**: SSE-streamed request log in the options page.
- **Auto TLS cert regeneration**: New domains trigger automatic `mkcert` cert regen.
- **Built-in LAN DNS server**: UDP DNS server on port 53 for zero-config LAN device routing.

## Quick Start (Automated - Windows)

1. **Right-click `server/setup_and_run.bat` and choose "Run as Administrator"** (this is only needed once to automatically install Python dependencies and configure local network Windows Firewall rule exceptions).
2. The script will configure everything and launch the server.
3. Access the control plane at `http://127.0.0.1:9080/` or click the local HTA dashboard `control_panel.hta`.

*(Note: Standard users do not need to run as administrator on subsequent startups. Running `python manage.py start` in any normal Command Prompt or starting via the HTA Control Panel is fully supported.)*

## Quick Start (Manual - Windows/macOS/Linux)

1. Install dependencies:
```bash
# Windows
py -m pip install -r server\requirements.txt

# macOS / Linux
pip install -r server/requirements.txt
```

2. Install trusted local CA and certs:
```bash
python manage.py certs --install
```

3. Start everything:
```bash
python manage.py start
```

4. Load extension in Chrome:
   1. Open `chrome://extensions`
   2. Enable Developer mode
   3. Click `Load unpacked`
   4. Select the project directory

5. Open popup and use Local mode toggle.

## Core Commands

Cross-platform CLI (`manage.py`):
```bash
python manage.py start               # Start the server stack
python manage.py stop                # Stop all server processes
python manage.py certs               # Regenerate TLS certificates
python manage.py certs --install     # Install CA + generate certs
python manage.py sync-domains        # Sync website dirs to domains.txt
python manage.py sync-domains --update-cert  # Sync + regenerate cert
python manage.py new-pack --pack nextjs --domain myapp.fake  # Scaffold
python manage.py status              # Show current server status
```

Legacy (Windows only):
```powershell
start_all.bat
stop_all.bat
```

Full listener check:
```powershell
netstat -aon | findstr :9080
netstat -aon | findstr :9081
netstat -aon | findstr :443
netstat -aon | findstr :53
```

## One-Time Setup

Python deps:
```bash
pip install -r server/requirements.txt
```

mkcert CA + cert generation:
```bash
python manage.py certs --install
```

Regenerate cert only:
```bash
python manage.py certs
```

Optional TLD list import:
```powershell
powershell -ExecutionPolicy Bypass -File server\import_tld_list.ps1 -InputJson C:\Users\XIA\Downloads\tld-list-details.json
```

References:
- `https://github.com/FiloSottile/mkcert`
- `https://tld-list.com/free-downloads`

## directory.json Schema (v3.0)

Each site folder (`server/websites/<domain>/`) can contain a `directory.json` with the following fields:

```json
{
  "entry": "index.html",
  "latencyMs": 200,
  "watermark": {
    "enabled": true,
    "text": "STAGING",
    "color": "#f59e0b"
  },
  "headers": {
    "request": {
      "set": { "X-Custom-Auth": "dev-token" },
      "remove": ["Cookie"]
    },
    "response": {
      "set": { "X-Robots-Tag": "noindex" }
    }
  },
  "backend": {
    "origin": "http://127.0.0.1:3000",
    "type": "node",
    "profile": "nextjs",
    "healthPath": "/",
    "wsPath": "/ws",
    "timeout": 25.0
  },
  "routes": [
    {
      "path": "/api/mock/*",
      "action": "mock",
      "status": 200,
      "contentType": "application/json",
      "body": { "ok": true, "message": "mocked" }
    },
    {
      "path": "/api/backend/*",
      "action": "proxy",
      "target": "http://127.0.0.1:5000"
    },
    {
      "path": "/static/*",
      "action": "static",
      "target": "./public"
    }
  ]
}
```

### Field Reference

| Field | Type | Description |
|---|---|---|
| `entry` | string | Entry file (default: `index.html`) |
| `latencyMs` | integer | Artificial delay in ms added to every request |
| `watermark.enabled` | boolean | Show a fixed dev banner on HTML pages |
| `watermark.text` | string | Banner text |
| `watermark.color` | string | Banner background color |
| `headers.request.set` | object | Headers to add/override on incoming requests |
| `headers.request.remove` | array | Header names to strip from incoming requests |
| `headers.response.set` | object | Headers to add/override on outgoing responses |
| `backend.origin` | string | Backend server URL (e.g., `http://127.0.0.1:3000`) |
| `backend.type` | string | Backend type hint (`php`, `node`, `python`) |
| `backend.profile` | string | Preset profile name |
| `routes[].path` | string | Glob pattern to match (e.g., `/api/*`) |
| `routes[].action` | string | `mock`, `proxy`, or `static` |

## Extension UI

Popup (Chrome):
- Local mode toggle (real domains)
- **Quick-add button**: one-click add/remove current domain from local list
- Quick actions: enable/disable proxy, reset locals, clear site data
- Backend origin quick edit
- Metrics summary
- Open options page

Popup behavior notes:
- Fake TLD rows are read-only local.
- If server is offline, toggle behavior is limited to routing state controls.
- `Disable proxy` is the fastest escape hatch for proxy-loop or server-down scenarios.

Options page:
- Proxy routing on/off
- Local domain allowlist management
- Per-domain backend config (`entry`, `backendOrigin`, `backendType`, `backendProfile`, `backendHealthPath`, `backendWsPath`)
- Backend test (HTTP + WS)
- Domain health snapshot
- Metrics view

Options page recommended workflow:
1. Set routing policy (`proxyEnabled` + `localDomains`).
2. Load domain config and set backend fields if dynamic app is used.
3. Run backend probe with optional `wsPath`.
4. Run health snapshot for all or selected domains.
5. Check metrics for latency/regression tracking.

## Server API

All control-plane endpoints are bound to `0.0.0.0` (accessible over the local network) under:
- `http://<server-ip>:9080/__xai/*`

If `XAI_CTRL_TOKEN` is set, include:
- header: `X-XAI-Token: <token>`
or
- query param: `?token=<token>`

### Domain Routing Options (Option A, B & C)

Network traffic must be routed to the local Domain Extension server to resolve and load `.fake` web pages. There are three ways to do this:

#### 1️⃣ Option A: Zero-Config DNS Server (Recommended System-Wide)
By pointing your client device's DNS server to the PC's LAN IP address, the built-in DNS server handles resolution automatically.
* **PC Local Loopback:** Set your Windows Network Adapter DNS to `127.0.0.1`.
* **Mobile / LAN Devices:** Set your phone/tablet Wi-Fi DNS settings to Manual/Static and enter your PC's LAN IP (e.g. `192.168.254.101`).
* **Relay Behavior:** All `.fake` and registered local domains are resolved to the PC. Standard internet requests (like `google.com`) are relayed directly to public DNS.

#### 2️⃣ Option B: System Proxy (PAC File Setup)
Allows the operating system to selectively route only registered and fake domains through the proxy, bypassing for all other requests.
* **Host PC:** Configure your Windows Proxy Settings Setup Script to: `http://127.0.0.1:9080/__xai/proxy.pac`
* **Mobile / LAN Devices:** Set the Wi-Fi connection proxy settings to **Automatic (PAC)** and enter the URL: `http://<your-pc-ip>:9080/__xai/proxy.pac`

#### 3️⃣ Option C: Browser Extension
Load the custom extension in your browser to handle proxy routing on a per-tab basis without changing any operating system or network adapter settings.
* **Installation:** Open `chrome://extensions` in Chrome/Edge, enable **Developer Mode**, click **Load unpacked**, and select the project root folder.

Status:
```powershell
curl.exe -sS "http://127.0.0.1:9080/__xai/status?domain=www.google.com"
```

Metrics:
```powershell
curl.exe -sS "http://127.0.0.1:9080/__xai/metrics?top=20"
```

Site config:
```powershell
curl.exe -sS "http://127.0.0.1:9080/__xai/site-config?domain=phpdemo.fake"
```

Backend profiles:
```powershell
curl.exe -sS "http://127.0.0.1:9080/__xai/backend-profiles"
```

Backend probe (HTTP + WS):
```powershell
curl.exe -sS "http://127.0.0.1:9080/__xai/backend-probe?domain=phpdemo.fake&wsPath=/ws"
```

Domain health:
```powershell
curl.exe -sS "http://127.0.0.1:9080/__xai/health?max=50"
```

### Endpoint reference (quick semantics)
- `/status?domain=...`
  - Returns effective mode defaults, local site presence, fake-TLD flag, hosts mapping visibility.
- `/metrics?top=N`
  - Returns request totals, mode split, status-class split, top domains, average latency.
- `/site-config?domain=...` (GET)
  - Reads `server/websites/<domain>/directory.json` interpreted config.
- `/site-config` (POST)
  - Writes per-domain config (`entry`, backend fields).
- `/backend-profiles`
  - Returns built-in profile templates.
- `/backend-probe?domain=...&wsPath=...`
  - Performs HTTP probe and WS connect probe against configured backend.
- `/health?...`
  - Bulk per-domain summary with probe results.
- `/ca` (GET)
  - Downloads the CA root certificate file directly to mobile/client devices.
- `/view/{domain}` (GET)
  - Standard HTTP proxy routing page to bypass mobile HSTS blocks on target domains (e.g. `http://<lan-ip>:9080/__xai/view/www.google.com`).
- `/client-overrides` (GET, POST, DELETE)
  - CRUD operations to manage IP-specific routing rules on tethered mobile devices.
- `/github/list`, `/github/status`
  - Returns text output from GitHub mapping/status commands.
- `/github/add`, `/github/pull`, `/github/pull-all`, `/github/remove`
  - Mutating GitHub source actions for domain-repo management.
- `/___xai/portal?domain=...`
  - Served HTML routing toggle dashboard on virtual hosts to let LAN clients override routing mode.
- `/___xai/client-mode`
  - Sets client routing override mode for the requester's IP address.

## Backend Config Schema

Per-domain config file:
- `server\websites\<domain>\directory.json`

Minimal:
```json
{
  "entry": "index.html"
}
```

With backend:
```json
{
  "entry": "index.html",
  "backend": {
    "origin": "http://127.0.0.1/phpdemo",
    "type": "php",
    "profile": "php-xampp",
    "healthPath": "/",
    "wsPath": "/ws"
  }
}
```

Field details:
- `entry`: local static entry file when serving static local site.
- `backend.origin`: local backend base URL for dynamic mode.
- `backend.type`: metadata (`php`, `node`, `python`, `static`) for management clarity.
- `backend.profile`: optional profile id from `/backend-profiles`.
- `backend.healthPath`: optional path appended during health/probe HTTP checks.
- `backend.wsPath`: optional websocket path used in health/probe defaults.

Resolution behavior:
- If backend exists and is allowed, backend mode is used for that domain in local flow.
- If backend is missing, static local files are used.
- If neither local file nor backend result is available, upstream fallback applies by mode rules.

## PHP / XAMPP Example

Ready example files:
- `examples\phpdemo-xampp\index.php`
- `examples\phpdemo-xampp\api.php`
- `server\websites\phpdemo.fake\directory.json`

Use:
1. Copy example files to `C:\xampp\htdocs\phpdemo\`
2. Start Apache in XAMPP
3. Run `start_all.bat`
4. Open `https://phpdemo.fake/`

Common path mismatch checks:
- `http://127.0.0.1/phpdemo/` should load directly before testing through fake domain.
- If direct URL fails, fix XAMPP path/Apache first.
- If direct URL works but fake domain fails, inspect `directory.json` backend origin.

## Tooling Scripts

### Domain and cert sync

Sync website domains into `server\domains.txt`:
```powershell
powershell -ExecutionPolicy Bypass -File server\sync_domains.ps1
```

Sync + regenerate cert if changed:
```powershell
powershell -ExecutionPolicy Bypass -File server\sync_domains.ps1 -UpdateCert
```

### GitHub sync

Use this when local site source lives in GitHub and you want repeatable updates without manual copy.

UI option:
- Options page -> `GitHub Sources` panel (add/list/status/pull/pull-all/remove)
- This calls control-plane GitHub endpoints (which run `server\github_sync.ps1` under the hood).

List:
```powershell
powershell -ExecutionPolicy Bypass -File server\github_sync.ps1 list
```

Add/update source:
```powershell
powershell -ExecutionPolicy Bypass -File server\github_sync.ps1 add mysite.fake https://github.com/<owner>/<repo>.git main
```

Pull one:
```powershell
powershell -ExecutionPolicy Bypass -File server\github_sync.ps1 pull mysite.fake
```

Pull all:
```powershell
powershell -ExecutionPolicy Bypass -File server\github_sync.ps1 pull-all
```

Status:
```powershell
powershell -ExecutionPolicy Bypass -File server\github_sync.ps1 status
```

Remove mapping:
```powershell
powershell -ExecutionPolicy Bypass -File server\github_sync.ps1 remove mysite.fake -KeepFiles
```

Template note:
- GitHub itself does not need a special template in this project.
- You can point a domain at any repo URL.
- If you want starter repos, use the local pack templates (`server\new_pack.ps1`) and push generated output to your own GitHub repo.

### Dev environment packs

Scaffold pack:
```powershell
powershell -ExecutionPolicy Bypass -File server\new_pack.ps1 -Pack php-xampp -Domain shop.fake -Project shop
```

Supported packs:
- `php-xampp`
- `node-express`
- `wordpress-xampp`
- `laravel`

Template behavior:
- Copies pack `site` template into `server\websites\<domain>\`
- Generates backend starter from pack `backend` template into `examples\generated\<domain>-<pack>\`
- Replaces tokens in generated files:
  - `__DOMAIN__`
  - `__PACK__`
  - `__ORIGIN__`
  - `__PROJECT__`

### System-level Windows PAC mode (optional)

Use this only if you need routing outside extension-controlled browsers/apps.

Sync domains from `server\websites\*`:
```powershell
powershell -ExecutionPolicy Bypass -File server\system_proxy.ps1 sync
```

Enable PAC at user level:
```powershell
powershell -ExecutionPolicy Bypass -File server\system_proxy.ps1 enable
```

Status:
```powershell
powershell -ExecutionPolicy Bypass -File server\system_proxy.ps1 status
```

Disable PAC:
```powershell
powershell -ExecutionPolicy Bypass -File server\system_proxy.ps1 disable
```

## Browser Variants

Chrome/Chromium (primary):
- Use root extension (`manifest.json`)

Firefox variant:
- Files in `firefox\`
- Load temporary add-on from `firefox\manifest.json` in `about:debugging#/runtime/this-firefox`

Browser support nuance:
- Chromium extension path is the most complete and tested.
- Firefox variant is functional but intentionally lighter than Chromium options UI.
- Safari/Tor are out of scope for current implementation.

## Runtime Environment Variables

`XAI_CTRL_TOKEN`
- Optional auth token for control-plane endpoints.

`XAI_BACKEND_ALLOWLIST`
- Comma-separated additional hosts allowed for backend origin.
- Default allowed hosts: `127.0.0.1`, `localhost`, `::1`.

`XAI_UPSTREAM_ENGINE`
- Upstream proxy engine.
- Values: `auto`, `native`, `curl`.
- Default: `auto`.

`XAI_PROXY_PORT`
- Local proxy listener port (default `9081`).

`XAI_AUTO_HOSTS`
- Legacy hosts auto-reconcile toggle.
- Default behavior in this setup is effectively PAC-first (legacy only when explicitly used).

`XAI_FLUSH_DNS`
- Legacy hosts path DNS flush toggle when hosts operations are active.

## Troubleshooting

Proxy error after closing server:
- Use popup `Disable proxy`.
- If popup fails, disable extension in `chrome://extensions`.

Local appears enabled unexpectedly:
- Popup `Reset locals`.

`WinError 10061` from backend:
- Backend app is not running on configured `backend.origin`.
- Test backend directly first in browser.

Apache `Not Found`:
- Backend origin path does not match where files are located in `htdocs`.

PHP `strict_types` error:
- Save PHP files without BOM.

Fake domain shows not secure:
- Re-run `server\certs.ps1 -Install`, restart browser.

WebSocket backend issues:
- Use `/__xai/backend-probe` or Options `Test Backend (HTTP+WS)`.
- Verify `backendWsPath` and allowlist host.

Real domain slow or unreachable when server is off:
- Legacy hosts override may still be active.
- Run `stop_all.bat` or `server\hosts.ps1 disable`.

### Deeper troubleshooting matrix

Symptom: popup stuck on loading  
Check:
1. `chrome://extensions` -> reload extension
2. ensure active tab is `http(s)`, not `chrome://...`
3. test `curl.exe -sS "http://127.0.0.1:9080/__xai/status?domain=www.google.com"`

Symptom: toggle changes but page does not switch  
Check:
1. confirm `Proxy Routing` row in popup
2. hard reload active tab
3. use popup `Clear site data`
4. verify domain present/absent in `localDomains` via Options page

Symptom: official site loads slowly only in proxy path  
Check:
1. legacy hosts override is likely still mapping real domain to localhost
2. run `stop_all.bat` then start clean with `start_all.bat`
3. keep PAC mode as primary path

Symptom: backend probe HTTP OK, WS fail  
Check:
1. `wsPath` mismatch (set in config or probe parameter)
2. backend may require auth/cookie/header or specific handshake path
3. test WS endpoint directly with backend logs open

Symptom: cert warnings after adding new domains  
Check:
1. update `server/domains.txt` (or run sync script)
2. regenerate cert via `server\certs.ps1`
3. ensure CA trust still installed (`-Install` if needed)
4. restart browser

## First 30 Minutes Walkthrough (Detailed)

Goal:
- verify baseline stack is healthy
- verify fake domain local serving
- verify real domain toggle behavior
- verify backend dynamic mode

### Step 1: Install dependencies and certs
Run:
```powershell
pip install -r server\requirements.txt
powershell -ExecutionPolicy Bypass -File server\certs.ps1 -Install
```

Expected:
- pip reports installed/satisfied packages
- mkcert installs local CA and cert files under `server\certs\`

Validate:
```powershell
dir server\certs
```

### Step 2: Start stack
Run:
```powershell
start_all.bat
```

Expected listeners:
```powershell
netstat -aon | findstr :9080
netstat -aon | findstr :9081
netstat -aon | findstr :443
netstat -aon | findstr :53
```

Expected:
- all three show `LISTENING`

### Step 3: Load extension
Chrome path:
- `chrome://extensions` -> load unpacked -> repo root

Expected:
- popup opens and shows server `online` on normal web tabs

### Step 4: Validate control plane
Run:
```powershell
curl.exe -sS "http://127.0.0.1:9080/__xai/status?domain=www.google.com"
```

Expected:
- JSON with `domain`, `mode`, `hasLocalSite`, `serverVersion`

### Step 5: Fake domain local check
Open:
- `https://example.fake/`

Expected:
- local site content loads
- popup shows fake domain effectively local

### Step 6: Real domain switch check
Open:
- `https://www.google.com/`

Toggle in popup:
- Local OFF -> should load official site
- Local ON -> should route through local handling

Expected:
- URL unchanged
- behavior changes on reload

### Step 7: Backend dynamic check (XAMPP sample)
Direct backend:
- `http://127.0.0.1/phpdemo/` should work first

Then fake domain:
- `https://phpdemo.fake/`

Expected:
- dynamic PHP content

### Step 8: Probe and health
Run:
```powershell
curl.exe -sS "http://127.0.0.1:9080/__xai/backend-probe?domain=phpdemo.fake&wsPath=/ws"
curl.exe -sS "http://127.0.0.1:9080/__xai/health?max=50"
```

Expected:
- JSON output without transport errors

## Failure Injection and Recovery Lab

Use this section to intentionally break pieces and verify recovery playbooks.

### Scenario 1: Server-down while proxy still enabled
Inject:
1. Keep a real domain tab open
2. Stop server (`stop_all.bat` or close server window)

Expected failure:
- proxy/network error page

Recovery:
1. popup -> `Disable proxy`
2. if popup unavailable -> disable extension in `chrome://extensions`
3. reload tab

### Scenario 2: Backend refused (`WinError 10061`)
Inject:
1. Configure backend origin to local service port
2. stop that backend service

Expected failure:
- backend 502 with connection refused details

Recovery:
1. start backend service
2. verify direct backend URL
3. retest fake/real domain path

### Scenario 3: Wrong backend path (`Not Found`)
Inject:
1. point backend origin to wrong subpath

Expected:
- Apache/HTTP 404

Recovery:
1. fix `backend.origin`
2. validate direct URL first
3. reload routed URL

### Scenario 4: Local state confusion
Inject:
1. add multiple real domains to local allowlist
2. forget which ones are local

Recovery:
1. options page -> inspect local domains table
2. popup -> `Reset locals` to clear all
3. re-add only intended domains

### Scenario 5: Cert mismatch after domain changes
Inject:
1. add new domains without cert refresh

Expected:
- cert warning on some domains

Recovery:
```powershell
powershell -ExecutionPolicy Bypass -File server\sync_domains.ps1 -UpdateCert
```
Then restart browser.

### Scenario 6: Hosts override interference
Inject:
1. add real domain to legacy hosts
2. stop server

Expected:
- real domain unreachable or delayed

Recovery:
```powershell
stop_all.bat
```
or:
```powershell
powershell -ExecutionPolicy Bypass -File server\hosts.ps1 disable
```

## Developer File Guide (Per-File)

### Extension files (Chromium)
- `manifest.json`
  - Defines permissions, popup, service worker, options page.
  - Changes here usually require extension reload.
- `sw.js`
  - Owns PAC state and routing policy (`localDomains`, `proxyEnabled`).
  - If routing behavior is wrong, inspect this first.
- `popup.js`
  - Per-tab quick controls and recovery actions.
  - Good place for UX-level fixes.
- `options.js`
  - Advanced config/probe/health UI logic.
  - Good place for admin tooling enhancements.
- `popup.html`, `options.html`
  - UI structure only.

### Extension files (Firefox variant)
- `firefox/manifest.json`
  - Firefox-specific extension manifest.
- `firefox/background.js`
  - Uses `proxy.onRequest` instead of Chromium PAC API.
- `firefox/popup.js`, `firefox/popup.html`
  - Simplified popup controls.

### Server core
- `server/app.py`
  - Main system brain:
    - control-plane APIs
    - HTTPS vhost routing by Host header
    - local CONNECT proxy
    - backend proxy
    - upstream fetch engine
    - metrics and health endpoints
  - Most production behavior changes land here.
- `server/requirements.txt`
  - Python runtime dependencies.

### Server config and automation
- `server/domains.txt`
  - Cert SAN source list.
- `server/sync_domains.ps1`
  - Syncs website folders into `domains.txt`, optional cert update.
- `server/certs.ps1`
  - mkcert helper.
- `server/setup_and_run.bat`
  - Full startup flow.
- `server/run.ps1`, `server/run.bat`
  - Direct run helpers.
- `server/hosts.ps1`
  - Legacy hosts block control.
- `server/system_proxy.ps1`
  - System-level PAC mode control.
- `server/github_sync.ps1`, `server/github_sources.json`
  - GitHub source mapping/sync.
- `server/new_pack.ps1`, `server/packs/README.md`
  - Dev pack scaffolding.

### Site content layout
- `server/websites/<domain>/directory.json`
  - Domain behavior contract (entry/backend fields).
- `server/websites/<domain>/...`
  - Static site files or placeholder files.
- `examples/phpdemo-xampp/*`
  - Reference dynamic PHP sample.

### Operational rule of thumb
- If issue is "routing decision", inspect extension state/UI.
- If issue is "content served wrong", inspect `server/app.py` path and domain config.
- If issue is "TLS/security warning", inspect cert/domain sync and trust chain.
- If issue is "slow/blocked real domain", inspect hosts overrides and proxy mode.

## Legacy Hosts Mode (Optional)

Not recommended as default, but available:

Sync hosts block:
```powershell
powershell -ExecutionPolicy Bypass -File server\hosts.ps1 sync
```

Add one:
```powershell
powershell -ExecutionPolicy Bypass -File server\hosts.ps1 add www.google.com
```

Remove one:
```powershell
powershell -ExecutionPolicy Bypass -File server\hosts.ps1 remove www.google.com
```

Disable managed block:
```powershell
powershell -ExecutionPolicy Bypass -File server\hosts.ps1 disable
```
