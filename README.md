# Domain Extension v3.0

An advanced developer tool to hijack any web domain (e.g. `https://www.google.com` or custom `https://app.fake`) and redirect it to your local static files or local backend servers (PHP/XAMPP, Node.js, Python, Laravel, Wordpress) without altering your system `hosts` files.

---

## 🌟 Key Features

*   **FastAPI & Async Engine**: Upgraded backend from Flask to FastAPI + Uvicorn + HTTPX for high-throughput, non-blocking proxying and live WebSocket tunneling.
*   **Port-Free Access**: Binds the HTTPS vhost server to the standard HTTPS port (`443`) by default, enabling clean URLs without port suffixes (e.g., `https://dashboard.fake/`).
*   **HTA CRUD Dashboard**: Native Windows control center GUI (`control_panel.hta`) providing full Create, Read, Update, Delete (CRUD) operations for scaffolding websites, managing mobile settings, and syncing GitHub repos.
*   **Wildcard Subdomain Routing**: Extension PAC routing supports both exact domains and wildcard subdomains (e.g., `*.google.com` matches all subdomains).
*   **Local Network (LAN) & Mobile Support**: Built-in UDP DNS server intercepts fake-TLD queries. Trust local HTTPS pages by visiting `http://<lan-ip>:9080/__xai/ca` directly on your mobile device.
*   **Tethered Devices & Overrides**: Route target domains for specific mobile device IPs to either local mock folders or proxy them to original live sites to bypass HSTS and SSL warnings.
*   **GitHub Repos Sync**: Map custom domains to public/private GitHub repositories, configuring branches and pulling updates with a single click.
*   **API Mocking**: Return canned JSON/text mock responses directly from your `directory.json` configuration for specified path globs.
*   **Developer Watermark/Banner**: Inject custom coloured overlay banners into HTML responses automatically.
*   **Styled Directory Explorer**: Visually appealing, interactive folder listings when the main entry file (`index.html`) is missing in a website's folder.
*   **Live Request Dashboard**: Real-time request telemetry logs streamed directly via Server-Sent Events (SSE) into the options page and HTA GUI.

---

## 🛠️ Quick Start

### 1. Install Dependencies
```bash
# Windows
py -m pip install -r server/requirements.txt

# macOS / Linux
pip install -r server/requirements.txt
```

### 2. Install Trusted CA & Certificates
Ensure `mkcert` is installed, then run:
```bash
python manage.py certs --install
```

### 3. Start the Server Stack
```bash
# Using the CLI
python manage.py start

# Or double-click the HTA GUI in Windows Explorer:
control_panel.hta
```

### 4. Install Browser Extension
1.  Open Chrome and navigate to `chrome://extensions`.
2.  Enable **Developer mode** (top right).
3.  Click **Load unpacked** (top left).
4.  Select the root folder of this project.

---

## 🖥️ HTA CRUD Control Center
 
The native Windows control center (`control_panel.hta`) allows you to manage all aspects of the application visually:
 
1.  **Launch & Status Monitoring**: Pulsing status indicators displaying server state, and buttons to Start, Stop, or Regenerate Certificates.
2.  **Create Websites**: Quickly scaffold new website folders using built-in framework templates (NextJS, Vite React, php-xampp, Laravel, WordPress).
3.  **Config Editor**: Edit entry files, inject latency delays, setup developer watermark text/colors, configure local backend proxy parameters, or manage mock routes without touching JSON files.
4.  **Tethered Devices & Overrides**: Add/remove overrides for specific device IPs, get CA trust certificate installation instructions, and LAN URLs.
5.  **GitHub Deployment rules**: Connect domains directly to GitHub repositories, check branch status, and trigger Git pull operations.
6.  **Delete Websites**: Clean up directory folders and rebuild domain configuration files in one click.

---

## 🌐 Domain Routing Options (Host & LAN Devices)

To load local `.fake` websites in your browser, the network traffic must be routed to the local server. You can achieve this using any of the following three options:

### 1️⃣ Option A: Zero-Config DNS Server (Recommended)
By pointing your device's DNS settings to the PC's IP, the PC will resolve all `.fake` domains locally while relaying other internet traffic.
* **For Host PC:** Change your Windows network adapter DNS to `127.0.0.1`.
* **For LAN Devices (Phone/Tablet):**
  1. Open your phone's **Wi-Fi Settings > DNS**.
  2. Change from *Automatic* to *Manual* / *Static*.
  3. Set the DNS address to your PC's LAN IP (e.g. `192.168.254.101`).
  4. Now visit any local site (e.g., `https://blog.fake`).
* **Pros:** Works system-wide across all apps and browsers. No software installation needed on client devices.

### 2️⃣ Option B: System Proxy (PAC File)
Uses a Proxy Auto-Config (PAC) script to selectively route only `.fake` and registered local domains to the server.
* **For Host PC:** Go to **Windows Settings > Network & Internet > Proxy**. Turn on **Use setup script** and set the Script address to `http://127.0.0.1:9080/__xai/proxy.pac`.
* **For LAN Devices (Phone/Tablet):**
  1. Open **Wi-Fi Settings > Proxy**.
  2. Select **Automatic (PAC)** and enter the URL: `http://<your-pc-ip>:9080/__xai/proxy.pac`.
* **Pros:** Normal internet traffic is completely untouched (bypasses the proxy), making it very fast. No DNS configuration required.

### 3️⃣ Option C: Browser Extension
Use the custom Chrome/Firefox extension provided in this repository to route traffic dynamically on a per-tab basis.
* **How to install on Host PC:**
  1. Open Chrome/Edge and go to `chrome://extensions`.
  2. Enable **Developer Mode** (toggle in the top-right).
  3. Click **Load unpacked** and select the repository root folder.
* **Pros:** Highly flexible. Lets you quickly toggle local routing on/off, inject latency, mock APIs, and view live requests directly from your browser toolbar. No system-wide network changes.

---

## 📱 Local Network (LAN) Setup

Follow these steps to configure your environment for mobile testing:

### Step 1: Automated Configuration & Launch
1. **Right-click `server/setup_and_run.bat` and select "Run as Administrator"** (this is only required the first time to automatically configure Windows Firewall rules for ports `53`, `443`, `9080`, and `9081`).
2. The script will install dependencies, add firewall exceptions, generate local TLS certs, and start the services.
3. The console will print your detected LAN IP address (e.g. `192.168.254.101`).

*(Note: On subsequent runs, you can launch the server normally via Command Prompt or the HTA Control Panel.)*

### Step 2: Configure Trust Certificate on Phone
Your phone must trust the local development certificate for HTTPS to work:
1. **Direct Download (easiest)**: Open your phone's browser and go to `http://<your-pc-ip>:9080/__xai/ca` to download the root CA certificate file directly.
2. **Or Manual Export**: Run `extract_ca.bat` on your PC, then send the copied `rootCA.pem` to your phone (email, AirDrop, etc.).
3. **On iOS**: Go to **Settings > Profile Downloaded > Install**, then go to **Settings > General > About > Certificate Trust Settings** and enable full trust for *mkcert*.
4. **On Android**: Go to **Settings > Security > Encryption & Credentials > Install a Certificate > CA Certificate** and select the downloaded file.

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|---|---|---|
| `XAI_DNS_ENABLED` | `1` | Set to `0` to disable the built-in DNS server |
| `XAI_DNS_HOST` | `0.0.0.0` | Bind address for the DNS server |
| `XAI_DNS_PORT` | `53` | UDP port for the DNS server (use `5353` to avoid admin) |
| `XAI_PROXY_HOST` | `0.0.0.0` | Bind address for the CONNECT proxy |
| `XAI_PROXY_PORT` | `9081` | Port for the CONNECT proxy |
| `XAI_CTRL_TOKEN` | *(empty)* | Optional auth token for the control plane API |
| `XAI_CLEAR_SITE_DATA` | `1` | Set to `0` to disable Clear-Site-Data headers |
---

## 📂 Project Structure

*   `control_panel.hta` – GUI control center for Windows.
*   `manage.py` – Unified cross-platform developer CLI.
*   `sw.js` – Chrome Manifest V3 proxy PAC service worker.
*   `firefox/` – Firefox browser extension source.
*   `server/` – Backend FastAPI application core.
    *   `app.py` – FastAPI core server.
    *   `websites/` – Directories containing local websites and `directory.json` files.
    *   `packs/` – Scaffolding templates.
*   `documentation.md` – In-depth configuration and architecture reference.
