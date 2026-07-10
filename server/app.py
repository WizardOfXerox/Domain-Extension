"""Domain Extension – FastAPI-based control plane, HTTPS vhost, CONNECT proxy, and LAN DNS.

Upgraded from Flask to FastAPI with:
- Async upstream fetching via httpx (replaces curl.exe subprocesses)
- Path-based routing rules, API mocking, header injection, latency simulation
- Developer watermark/banner injection for HTML responses
- Styled directory explorer when entry file is missing
- Live request log streaming via SSE endpoint
- Auto TLS cert regeneration when new domains are registered
- Built-in UDP DNS server for LAN-wide fake-TLD resolution
"""

import argparse
import asyncio
import ctypes
import fnmatch
import html
import http.client
import json
import logging
import struct
import mimetypes
import os
import select
import shutil
import socket
import socketserver
import subprocess
import contextvars
import threading
import time
import urllib.parse
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

_dns_overrides = contextvars.ContextVar("_dns_overrides", default={})
_orig_getaddrinfo = socket.getaddrinfo

def _custom_getaddrinfo(*args, **kwargs):
    host = args[0]
    overrides = _dns_overrides.get()
    if host in overrides:
        new_args = list(args)
        new_args[0] = overrides[host]
        return _orig_getaddrinfo(*new_args, **kwargs)
    return _orig_getaddrinfo(*args, **kwargs)

socket.getaddrinfo = _custom_getaddrinfo

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.middleware.cors import CORSMiddleware

try:
    from websocket import create_connection as ws_create_connection
except Exception:  # pragma: no cover
    ws_create_connection = None  # type: ignore

try:
    import dns.resolver  # type: ignore
except Exception:  # pragma: no cover
    dns = None

LOG = logging.getLogger("xai")

FAKE_TLDS = (".fake", ".test", ".custom", ".ssx")
UPSTREAM_DNS = ["1.1.1.1", "8.8.8.8"]

HERE = os.path.abspath(os.path.dirname(__file__))
BASE_DIR = os.path.join(HERE, "websites")
STATE_PATH = os.path.join(HERE, "override_state.json")
CLIENT_OVERRIDES_FILE = os.path.join(HERE, "client_overrides.json")
CLIENT_OVERRIDES: Dict[str, Dict[str, str]] = {}
CLIENT_OVERRIDES_LOCK = threading.Lock()


def _load_client_overrides() -> None:
    global CLIENT_OVERRIDES
    if os.path.exists(CLIENT_OVERRIDES_FILE):
        try:
            with open(CLIENT_OVERRIDES_FILE, "r", encoding="utf-8") as f:
                CLIENT_OVERRIDES = json.load(f)
            LOG.info("Loaded client overrides from %s", CLIENT_OVERRIDES_FILE)
        except Exception as e:
            LOG.warning("Failed to load client overrides: %s", e)


def _save_client_overrides() -> None:
    with CLIENT_OVERRIDES_LOCK:
        try:
            with open(CLIENT_OVERRIDES_FILE, "w", encoding="utf-8") as f:
                json.dump(CLIENT_OVERRIDES, f, indent=2)
        except Exception as e:
            LOG.warning("Failed to save client overrides: %s", e)


def _get_client_mode(client_ip: Optional[str], domain: str) -> Optional[str]:
    if not client_ip:
        return None
    with CLIENT_OVERRIDES_LOCK:
        return CLIENT_OVERRIDES.get(client_ip, {}).get(domain.lower())


def _set_client_mode(client_ip: Optional[str], domain: str, mode: str) -> None:
    if not client_ip:
        return
    with CLIENT_OVERRIDES_LOCK:
        if client_ip not in CLIENT_OVERRIDES:
            CLIENT_OVERRIDES[client_ip] = {}
        if mode in ("local", "proxy"):
            CLIENT_OVERRIDES[client_ip][domain.lower()] = mode
        else:
            CLIENT_OVERRIDES[client_ip].pop(domain.lower(), None)
            if not CLIENT_OVERRIDES[client_ip]:
                CLIENT_OVERRIDES.pop(client_ip, None)
    _save_client_overrides()

    # Sync global site config mode (default to local if cleared)
    target_global_mode = mode if mode in ("local", "proxy") else "local"
    try:
        cfg_existing = _read_site_config(domain)
        backend_existing = cfg_existing.get("backend") or {}
        _write_site_config(
            domain=domain,
            entry=cfg_existing.get("entry") or "index.html",
            backend_origin=backend_existing.get("origin") or "",
            backend_type=backend_existing.get("type") or "",
            backend_profile=backend_existing.get("profile") or "",
            backend_health_path=backend_existing.get("healthPath") or "",
            backend_ws_path=backend_existing.get("wsPath") or "",
            mode=target_global_mode,
        )
        LOG.info("Sync global config mode for %s to %s", domain, target_global_mode)
    except Exception as e:
        LOG.warning("Failed to sync global site config mode: %s", e)


def _get_ca_root_dir() -> str:
    if os.environ.get("XAI_CA_ROOT"):
        return os.environ.get("XAI_CA_ROOT")
    try:
        import subprocess
        res = subprocess.run(["mkcert", "-CAROOT"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            p = res.stdout.strip()
            if os.path.isdir(p):
                return p
    except Exception:
        pass
    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            p = os.path.join(local_appdata, "mkcert")
            if os.path.isdir(p):
                return p
    else:
        home = os.environ.get("HOME", "")
        if home:
            p_mac = os.path.join(home, "Library", "Application Support", "mkcert")
            if os.path.isdir(p_mac):
                return p_mac
            p_linux = os.path.join(home, ".local", "share", "mkcert")
            if os.path.isdir(p_linux):
                return p_linux
    return ""


GITHUB_SYNC_SCRIPT = os.path.join(HERE, "github_sync.ps1")
CERT_PATH = os.path.join(HERE, "certs", "cert.pem")
KEY_PATH = os.path.join(HERE, "certs", "key.pem")
HOSTS_PATH = os.path.join(
    os.environ.get("WINDIR", r"C:\Windows"), "System32", "drivers", "etc", "hosts"
)
HOSTS_START_TAG = "# Domain Extension start"
HOSTS_END_TAG = "# Domain Extension end"

DEFAULT_CLEAR_SITE_DATA = os.environ.get("XAI_CLEAR_SITE_DATA", "1").strip() not in (
    "0",
    "false",
    "False",
)

SERVER_VERSION = "3.0"
CTRL_TOKEN = os.environ.get("XAI_CTRL_TOKEN", "").strip()
BACKEND_ALLOWLIST_ENV = [
    x.strip().lower()
    for x in os.environ.get("XAI_BACKEND_ALLOWLIST", "").split(",")
    if x.strip()
]
DEFAULT_BACKEND_ALLOWLIST = {"127.0.0.1", "localhost", "::1"}

UPSTREAM_ENGINE = os.environ.get("XAI_UPSTREAM_ENGINE", "auto").strip().lower()

BACKEND_PROFILES = {
    "php-xampp": {
        "type": "php",
        "originHint": "http://127.0.0.1/<project>",
        "healthPath": "/",
        "wsPath": "",
    },
    "node-express": {
        "type": "node",
        "originHint": "http://127.0.0.1:3000",
        "healthPath": "/",
        "wsPath": "/socket.io/?EIO=4&transport=websocket",
    },
    "python-flask": {
        "type": "python",
        "originHint": "http://127.0.0.1:5000",
        "healthPath": "/",
        "wsPath": "",
    },
    "python-fastapi": {
        "type": "python",
        "originHint": "http://127.0.0.1:8000",
        "healthPath": "/",
        "wsPath": "/ws",
    },
    "wordpress-xampp": {
        "type": "php",
        "originHint": "http://127.0.0.1/wordpress",
        "healthPath": "/",
        "wsPath": "",
    },
    "laravel": {
        "type": "php",
        "originHint": "http://127.0.0.1:8000",
        "healthPath": "/",
        "wsPath": "/app",
    },
    "nextjs": {
        "type": "node",
        "originHint": "http://127.0.0.1:3000",
        "healthPath": "/",
        "wsPath": "",
    },
    "vite-react": {
        "type": "node",
        "originHint": "http://127.0.0.1:5173",
        "healthPath": "/",
        "wsPath": "",
    },
}

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

METRICS_LOCK = threading.Lock()
METRICS: Dict[str, Any] = {
    "startedAt": int(time.time()),
    "requestsTotal": 0,
    "byMode": {"local": 0, "proxy": 0, "unknown": 0},
    "statusClass": {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0},
    "domains": {},
    "latencyMsTotal": 0.0,
}


def _record_metric(domain: str, mode: str, status_code: int, latency_ms: float) -> None:
    if not domain:
        domain = "-"
    if mode not in ("local", "proxy"):
        mode = "unknown"

    if 200 <= status_code < 300:
        status_class = "2xx"
    elif 300 <= status_code < 400:
        status_class = "3xx"
    elif 400 <= status_code < 500:
        status_class = "4xx"
    elif 500 <= status_code < 600:
        status_class = "5xx"
    else:
        status_class = "other"

    with METRICS_LOCK:
        METRICS["requestsTotal"] += 1
        METRICS["byMode"][mode] = METRICS["byMode"].get(mode, 0) + 1
        METRICS["statusClass"][status_class] = METRICS["statusClass"].get(status_class, 0) + 1
        METRICS["latencyMsTotal"] += float(latency_ms)

        d = METRICS["domains"].get(domain)
        if not d:
            d = {
                "count": 0,
                "local": 0,
                "proxy": 0,
                "2xx": 0,
                "3xx": 0,
                "4xx": 0,
                "5xx": 0,
                "other": 0,
                "latencyMsTotal": 0.0,
            }
            METRICS["domains"][domain] = d

        d["count"] += 1
        d[mode] = d.get(mode, 0) + 1
        d[status_class] = d.get(status_class, 0) + 1
        d["latencyMsTotal"] += float(latency_ms)


def _metrics_snapshot(top_domains: int = 20) -> dict:
    with METRICS_LOCK:
        total = int(METRICS["requestsTotal"])
        avg = (float(METRICS["latencyMsTotal"]) / total) if total else 0.0
        items = []
        for domain, stats in METRICS["domains"].items():
            c = int(stats.get("count", 0))
            items.append(
                {
                    "domain": domain,
                    "count": c,
                    "local": int(stats.get("local", 0)),
                    "proxy": int(stats.get("proxy", 0)),
                    "status": {
                        "2xx": int(stats.get("2xx", 0)),
                        "3xx": int(stats.get("3xx", 0)),
                        "4xx": int(stats.get("4xx", 0)),
                        "5xx": int(stats.get("5xx", 0)),
                        "other": int(stats.get("other", 0)),
                    },
                    "avgLatencyMs": (float(stats.get("latencyMsTotal", 0.0)) / c) if c else 0.0,
                }
            )
        items.sort(key=lambda x: x["count"], reverse=True)

        return {
            "serverVersion": SERVER_VERSION,
            "startedAt": int(METRICS["startedAt"]),
            "uptimeSec": int(time.time()) - int(METRICS["startedAt"]),
            "requestsTotal": total,
            "avgLatencyMs": avg,
            "byMode": dict(METRICS["byMode"]),
            "statusClass": dict(METRICS["statusClass"]),
            "topDomains": items[: max(1, top_domains)],
            "lanIp": _get_lan_ip(),
        }


# ---------------------------------------------------------------------------
# Live Request Log (SSE streaming)
# ---------------------------------------------------------------------------

MAX_LOG_ENTRIES = 500
_log_entries: deque = deque(maxlen=MAX_LOG_ENTRIES)
_log_event = asyncio.Event()


def _push_log_entry(entry: dict) -> None:
    _log_entries.append(entry)
    try:
        _log_event.set()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HOP_BY_HOP = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "accept-encoding",
})


def _is_backend_origin_allowed(origin: str) -> bool:
    try:
        u = urllib.parse.urlparse(origin)
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    host = (u.hostname or "").strip().lower()
    if not host:
        return False
    allow = set(DEFAULT_BACKEND_ALLOWLIST)
    allow.update(BACKEND_ALLOWLIST_ENV)
    return host in allow


def _list_local_domains() -> list[str]:
    try:
        if not os.path.isdir(BASE_DIR):
            return []
        out = []
        for name in os.listdir(BASE_DIR):
            p = os.path.join(BASE_DIR, name)
            if os.path.isdir(p):
                out.append(name.strip().lower())
        return sorted(set([x for x in out if x]))
    except Exception:
        return []


def _domain_from_host(host: str) -> str:
    return host.split(":", 1)[0].strip().lower()


def _is_fake_tld(domain: str) -> bool:
    return any(domain.endswith(tld) for tld in FAKE_TLDS)


def _default_mode(domain: str) -> str:
    if _is_fake_tld(domain):
        return "local"
    if _has_local_site(domain):
        cfg = _read_site_config(domain)
        if cfg.get("mode") == "proxy":
            return "proxy"
        return "local"
    return "proxy"


def _site_root(domain: str) -> str:
    return os.path.join(BASE_DIR, domain)


def _has_local_site(domain: str) -> bool:
    return os.path.isdir(_site_root(domain))


def _guess_content_type(path: str, default: str = "application/octet-stream") -> str:
    ctype, _enc = mimetypes.guess_type(path)
    return ctype or default


def _safe_path(root: str, req_path: str) -> str:
    rel = (req_path or "/").split("?", 1)[0]
    rel = rel.lstrip("/")
    joined = os.path.normpath(os.path.join(root, rel))
    root_norm = os.path.normpath(root)
    if joined == root_norm:
        return joined
    if not joined.startswith(root_norm + os.sep):
        return ""
    return joined


# ---------------------------------------------------------------------------
# Site Config (new schema)
# ---------------------------------------------------------------------------

def _read_site_config(domain: str) -> dict:
    """Read per-site config supporting the new expanded schema.

    Returns a dict with keys:
      entry, backend, latencyMs, watermark, headers, routes
    """
    cfg_path = os.path.join(_site_root(domain), "directory.json")
    result = {
        "mode": "local",
        "entry": "index.html",
        "backend": None,
        "latencyMs": 0,
        "watermark": {"enabled": False, "text": "DEVELOPMENT", "color": "#ef4444"},
        "headers": {"request": {"set": {}, "remove": []}, "response": {"set": {}}},
        "routes": [],
    }

    if not os.path.exists(cfg_path):
        return result

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            return result

        result["mode"] = str(cfg.get("mode") or "local").strip().lower()
        result["entry"] = cfg.get("entry") or cfg.get("index") or cfg.get("main") or "index.html"

        # Latency
        try:
            result["latencyMs"] = max(0, int(cfg.get("latencyMs", 0)))
        except (ValueError, TypeError):
            pass

        # Watermark
        wm = cfg.get("watermark")
        if isinstance(wm, dict):
            result["watermark"] = {
                "enabled": bool(wm.get("enabled", False)),
                "text": str(wm.get("text", "DEVELOPMENT")),
                "color": str(wm.get("color", "#ef4444")),
            }

        # Headers
        hdrs = cfg.get("headers")
        if isinstance(hdrs, dict):
            req_h = hdrs.get("request")
            if isinstance(req_h, dict):
                result["headers"]["request"]["set"] = dict(req_h.get("set", {}))
                rm = req_h.get("remove", [])
                result["headers"]["request"]["remove"] = list(rm) if isinstance(rm, list) else []
            res_h = hdrs.get("response")
            if isinstance(res_h, dict):
                result["headers"]["response"]["set"] = dict(res_h.get("set", {}))

        # Routes
        routes = cfg.get("routes")
        if isinstance(routes, list):
            for r in routes:
                if isinstance(r, dict) and r.get("path") and r.get("action"):
                    result["routes"].append(r)

        # Backend (legacy + new)
        b = cfg.get("backend")
        if isinstance(b, dict):
            origin = str(b.get("origin") or "").strip()
            if origin:
                result["backend"] = {
                    "origin": origin.rstrip("/"),
                    "timeout": float(b.get("timeout") or 25.0),
                    "profile": str(b.get("profile") or "").strip(),
                    "type": str(b.get("type") or "").strip(),
                    "healthPath": str(b.get("healthPath") or "/").strip(),
                    "wsPath": str(b.get("wsPath") or "").strip(),
                }
    except Exception as e:
        LOG.warning("Bad directory.json for %s: %s", domain, e)

    return result


def _write_site_config(
    domain: str,
    entry: Optional[str] = None,
    backend_origin: Optional[str] = None,
    backend_type: Optional[str] = None,
    backend_profile: Optional[str] = None,
    backend_health_path: Optional[str] = None,
    backend_ws_path: Optional[str] = None,
    mode: Optional[str] = None,
) -> dict:
    root = _site_root(domain)
    os.makedirs(root, exist_ok=True)
    cfg_path = os.path.join(root, "directory.json")

    out: dict = {}
    out["mode"] = str(mode or "local").strip().lower()

    if entry:
        out["entry"] = str(entry).strip() or "index.html"
    else:
        out["entry"] = "index.html"

    bo = (backend_origin or "").strip()
    if bo:
        out["backend"] = {"origin": bo}
        if (backend_type or "").strip():
            out["backend"]["type"] = str(backend_type).strip()
        if (backend_profile or "").strip():
            out["backend"]["profile"] = str(backend_profile).strip()
        hp = (backend_health_path or "").strip()
        if hp:
            out["backend"]["healthPath"] = hp
        wsp = (backend_ws_path or "").strip()
        if wsp:
            out["backend"]["wsPath"] = wsp

    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    return out


# ---------------------------------------------------------------------------
# Path route matching
# ---------------------------------------------------------------------------

def _match_route(routes: list, req_path: str) -> Optional[dict]:
    """Match the first route whose path pattern matches req_path."""
    for route in routes:
        pattern = route.get("path", "")
        if not pattern:
            continue
        if fnmatch.fnmatch(req_path, pattern):
            return route
        # Also match when pattern ends with /* and path is the base itself
        if pattern.endswith("/*") and req_path == pattern[:-2]:
            return route
    return None


# ---------------------------------------------------------------------------
# Watermark injection
# ---------------------------------------------------------------------------

def _inject_watermark(body: bytes, watermark: dict) -> bytes:
    """Inject a development banner into HTML body."""
    if not watermark.get("enabled"):
        return body
    text = html.escape(watermark.get("text", "DEVELOPMENT"))
    color = html.escape(watermark.get("color", "#ef4444"))
    banner = (
        f'<div id="xai-dev-banner" style="'
        f"position:fixed;bottom:0;left:0;right:0;z-index:999999;"
        f"background:{color};color:#fff;text-align:center;"
        f"padding:4px 12px;font:bold 12px/1.4 system-ui,sans-serif;"
        f"letter-spacing:0.5px;opacity:0.92;pointer-events:none;"
        f'">{text}</div>'
    )
    try:
        decoded = body.decode("utf-8")
        lower = decoded.lower()
        idx = lower.rfind("</body>")
        if idx != -1:
            decoded = decoded[:idx] + banner + decoded[idx:]
        else:
            decoded += banner
        return decoded.encode("utf-8")
    except Exception:
        return body + banner.encode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Styled directory explorer
# ---------------------------------------------------------------------------

def _render_directory_listing(domain: str, dir_path: str, url_path: str) -> str:
    """Render a styled HTML directory listing for local site folders."""
    entries = []
    try:
        for name in sorted(os.listdir(dir_path)):
            full = os.path.join(dir_path, name)
            is_dir = os.path.isdir(full)
            size = "" if is_dir else _format_size(os.path.getsize(full))
            icon = "📁" if is_dir else "📄"
            href = url_path.rstrip("/") + "/" + name + ("/" if is_dir else "")
            entries.append({"name": name, "href": href, "icon": icon, "size": size, "is_dir": is_dir})
    except Exception as e:
        return f"<html><body><h1>Error listing directory</h1><p>{html.escape(str(e))}</p></body></html>"

    rows = ""
    for e in entries:
        rows += (
            f'<tr>'
            f'<td style="padding:8px 16px">{e["icon"]}</td>'
            f'<td style="padding:8px 16px"><a href="{html.escape(e["href"])}" '
            f'style="color:#7dd3fc;text-decoration:none">{html.escape(e["name"])}</a></td>'
            f'<td style="padding:8px 16px;color:#94a3b8;text-align:right">{e["size"]}</td>'
            f'</tr>'
        )

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Index of {html.escape(url_path)} – {html.escape(domain)}</title>
  <style>
    body {{
      margin: 0; padding: 24px;
      font: 14px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: #0c0f14; color: #e7eef7;
    }}
    h1 {{ font-size: 18px; font-weight: 600; margin: 0 0 16px; color: #94a3b8; }}
    .domain {{ color: #7dd3fc; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 800px; }}
    tr:hover {{ background: #1a2332; }}
    tr {{ border-bottom: 1px solid #1e293b; }}
    a:hover {{ text-decoration: underline !important; }}
    .hint {{ color: #64748b; margin-top: 16px; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>Index of <span class="domain">{html.escape(domain)}</span>{html.escape(url_path)}</h1>
  <table>
    <thead>
      <tr style="border-bottom:2px solid #263248">
        <th style="padding:8px 16px;text-align:left;width:40px"></th>
        <th style="padding:8px 16px;text-align:left;color:#94a3b8">Name</th>
        <th style="padding:8px 16px;text-align:right;color:#94a3b8">Size</th>
      </tr>
    </thead>
    <tbody>
      {rows or '<tr><td colspan="3" style="padding:16px;color:#64748b">Empty directory</td></tr>'}
    </tbody>
  </table>
  <p class="hint">Domain Extension v{SERVER_VERSION} — Local directory explorer</p>
</body>
</html>"""


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ---------------------------------------------------------------------------
# LAN IP detection
# ---------------------------------------------------------------------------

_cached_lan_ip: Optional[str] = None


def _get_lan_ip() -> str:
    """Detect the PC's current LAN IP via a non-connecting UDP socket."""
    global _cached_lan_ip
    if _cached_lan_ip:
        return _cached_lan_ip
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Doesn't actually send data; just causes the OS to pick a route
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and ip != "0.0.0.0":
            _cached_lan_ip = ip
            return ip
    except Exception:
        pass
    _cached_lan_ip = "127.0.0.1"
    return _cached_lan_ip


# ---------------------------------------------------------------------------
# Built-in DNS server for LAN resolution
# ---------------------------------------------------------------------------

def _build_dns_a_response(query: bytes, ip_address: str) -> bytes:
    """Build a minimal DNS A-record response from a raw query packet."""
    if len(query) < 12:
        return b""
    txn_id = query[:2]
    # Standard response flags: QR=1, AA=1, RD=1, RA=1
    flags = b"\x85\x80"
    # QDCOUNT=1, ANCOUNT=1, NSCOUNT=0, ARCOUNT=0
    counts = b"\x00\x01\x00\x01\x00\x00\x00\x00"

    # Extract the question section from the query
    i = 12
    while i < len(query):
        length = query[i]
        if length == 0:
            i += 1
            break
        i += 1 + length
    # QTYPE(2) + QCLASS(2)
    question = query[12 : i + 4]

    # Build the answer: pointer to name in question (0xc00c), A record, IN class, TTL=60, RDLENGTH=4
    parts = ip_address.split(".")
    ip_bytes = struct.pack("BBBB", *[int(p) for p in parts])
    answer = (
        b"\xc0\x0c"  # pointer to name
        b"\x00\x01"  # TYPE A
        b"\x00\x01"  # CLASS IN
        b"\x00\x00\x00\x3c"  # TTL 60s
        b"\x00\x04"  # RDLENGTH 4
        + ip_bytes
    )

    return txn_id + flags + counts + question + answer


def _build_dns_empty_response(query: bytes) -> bytes:
    """Build a DNS NOERROR response with zero answer records.

    Used for AAAA and other non-A queries on intercepted domains so we don't
    relay them to upstream (which would return NXDOMAIN and break resolution).
    """
    if len(query) < 12:
        return b""
    txn_id = query[:2]
    # Response flags: QR=1, AA=1, RD=1, RA=1, RCODE=0 (NOERROR)
    flags = b"\x85\x80"
    # QDCOUNT=1, ANCOUNT=0, NSCOUNT=0, ARCOUNT=0
    counts = b"\x00\x01\x00\x00\x00\x00\x00\x00"

    # Extract the question section from the query
    i = 12
    while i < len(query):
        length = query[i]
        if length == 0:
            i += 1
            break
        i += 1 + length
    # QTYPE(2) + QCLASS(2)
    question = query[12 : i + 4]

    return txn_id + flags + counts + question


def _extract_dns_name(query: bytes) -> str:
    """Extract the queried domain name from a raw DNS query packet."""
    if len(query) < 12:
        return ""
    parts = []
    i = 12
    while i < len(query):
        length = query[i]
        if length == 0:
            break
        i += 1
        if i + length > len(query):
            break
        parts.append(query[i : i + length].decode("ascii", errors="replace"))
        i += length
    return ".".join(parts).lower()


def _is_dns_a_query(query: bytes) -> bool:
    """Check if the DNS query is for an A record (type 1, class IN)."""
    if len(query) < 12:
        return False
    # Navigate past the question name
    i = 12
    while i < len(query):
        length = query[i]
        if length == 0:
            i += 1
            break
        i += 1 + length
    if i + 4 > len(query):
        return False
    qtype = struct.unpack("!H", query[i : i + 2])[0]
    qclass = struct.unpack("!H", query[i + 2 : i + 4])[0]
    return qtype == 1 and qclass == 1  # A record, IN class

def _resolve_upstream_ip(domain: str) -> Optional[str]:
    import random
    domain = domain.strip().lower()
    if not domain:
        return None
    tx_id = random.randint(0, 65535)
    header = struct.pack("!HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
    question = bytearray()
    for part in domain.split("."):
        if not part:
            continue
        part_bytes = part.encode("ascii", errors="replace")
        question.append(len(part_bytes))
        question.extend(part_bytes)
    question.append(0)
    question.extend(struct.pack("!HH", 1, 1)) # Type A, Class IN
    packet = header + question
    
    for resolver in UPSTREAM_DNS:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            sock.sendto(packet, (resolver, 53))
            resp, _ = sock.recvfrom(512)
            sock.close()
            if len(resp) < 12:
                continue
            resp_tx_id = struct.unpack("!H", resp[:2])[0]
            if resp_tx_id != tx_id:
                continue
            ancount = struct.unpack("!H", resp[6:8])[0]
            if ancount == 0:
                continue
            i = 12
            while i < len(resp):
                length = resp[i]
                if length == 0:
                    i += 1
                    break
                i += 1 + length
            i += 4
            for _ in range(ancount):
                if i + 12 > len(resp):
                    break
                if (resp[i] & 0xc0) == 0xc0:
                    i += 2
                else:
                    while i < len(resp):
                        l = resp[i]
                        if l == 0:
                            i += 1
                            break
                        i += 1 + l
                if i + 10 > len(resp):
                    break
                atype, aclass, ttl, rdlen = struct.unpack("!HHIH", resp[i:i+10])
                i += 10
                if i + rdlen > len(resp):
                    break
                if atype == 1 and aclass == 1 and rdlen == 4:
                    return socket.inet_ntoa(resp[i:i+4])
                i += rdlen
        except Exception:
            try:
                sock.close()
            except Exception:
                pass
            continue
    return None


def _should_intercept_dns(name: str, client_ip: Optional[str] = None) -> bool:
    """Return True if this domain should resolve to the LAN IP."""
    if any(name.endswith(tld) for tld in FAKE_TLDS):
        return True

    # Check client-specific override first!
    if client_ip:
        client_mode = _get_client_mode(client_ip, name)
        if client_mode == "proxy":
            return False
        elif client_mode == "local":
            return True

    # Also intercept any domain that has a registered local site folder
    if name and os.path.isdir(os.path.join(BASE_DIR, name)):
        cfg = _read_site_config(name)
        if cfg.get("mode") == "proxy":
            return False
        return True
    return False


class _LanDnsProtocol(asyncio.DatagramProtocol):
    """Async UDP DNS protocol: intercepts fake TLDs, relays everything else."""

    def __init__(self) -> None:
        self.transport: Optional[asyncio.DatagramTransport] = None
        # Map txn_id -> client address for relay tracking
        self._pending: Dict[bytes, tuple] = {}

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if len(data) < 12:
            return
        name = _extract_dns_name(data)

        if _should_intercept_dns(name, client_ip=addr[0]):

            if _is_dns_a_query(data):
                # A record query for a fake/local domain -> return LAN IP
                lan_ip = _get_lan_ip()
                response = _build_dns_a_response(data, lan_ip)
                if response and self.transport:
                    self.transport.sendto(response, addr)
                LOG.debug("DNS intercept: %s -> %s (client %s)", name, lan_ip, addr[0])
            else:
                # AAAA or other query type for a fake/local domain ->
                # Return NOERROR with zero answers (NOT relay to upstream,
                # which would return NXDOMAIN and poison the resolver cache)
                response = _build_dns_empty_response(data)
                if response and self.transport:
                    self.transport.sendto(response, addr)
                LOG.debug("DNS intercept (empty): %s non-A query (client %s)", name, addr[0])
            return

        # Relay to upstream DNS (real external domains only)
        asyncio.ensure_future(self._relay_query(data, addr))

    async def _relay_query(self, data: bytes, client_addr: tuple) -> None:
        """Forward the raw DNS query to upstream and send the reply back."""
        loop = asyncio.get_event_loop()
        for upstream in UPSTREAM_DNS:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(3.0)
                sock.sendto(data, (upstream, 53))
                reply = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: sock.recv(4096)),
                    timeout=3.0,
                )
                sock.close()
                if reply and self.transport:
                    self.transport.sendto(reply, client_addr)
                return
            except Exception:
                try:
                    sock.close()
                except Exception:
                    pass
                continue
        LOG.warning("DNS relay failed for all upstreams (client %s)", client_addr[0])


async def _start_dns_server(host: str = "0.0.0.0", port: int = 53) -> Optional[asyncio.DatagramTransport]:
    """Start the built-in LAN DNS server. Returns the transport or None on failure."""
    loop = asyncio.get_event_loop()
    try:
        transport, _protocol = await loop.create_datagram_endpoint(
            _LanDnsProtocol,
            local_addr=(host, port),
        )
        lan_ip = _get_lan_ip()
        LOG.info("LAN DNS server: udp://%s:%s  (LAN IP: %s)", host, port, lan_ip)
        LOG.info(
            "  -> Set your phone/device DNS to %s to resolve .fake/.test/.custom/.ssx domains",
            lan_ip,
        )
        return transport
    except PermissionError:
        LOG.error(
            "DNS server failed: port %d requires admin/root privileges. "
            "Run the server as Administrator.",
            port,
        )
        return None
    except OSError as e:
        LOG.error("DNS server failed on %s:%d: %s", host, port, e)
        return None


# ---------------------------------------------------------------------------
# Upstream fetch (async httpx)
# ---------------------------------------------------------------------------

_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(25.0, connect=5.0),
            follow_redirects=True,
            verify=True,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _http_client


async def _upstream_fetch(domain: str, request: Request) -> Tuple[int, bytes, str]:
    """Fetch upstream content via httpx async client."""
    method = request.method.upper()
    path = request.url.path
    query = str(request.url.query) if request.url.query else ""
    url = f"https://{domain}{path}"
    if query:
        url += f"?{query}"

    headers: dict[str, str] = {"Host": domain}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP:
            continue
        if "\n" in v or "\r" in v:
            continue
        headers[k] = v

    body = None
    if method in ("POST", "PUT", "PATCH"):
        body = await request.body()

    client = _get_http_client()
    
    # Resolve real IP to bypass local loopback routing
    real_ip = _resolve_upstream_ip(domain)
    token = None
    if real_ip:
        token = _dns_overrides.set({domain: real_ip})
        
    try:
        resp = await client.request(
            method=method,
            url=url,
            headers=headers,
            content=body,
            follow_redirects=True,
        )
        ctype = resp.headers.get("content-type", "")
        if ";" in ctype:
            ctype = ctype.split(";", 1)[0].strip()
        if not ctype:
            ctype = _guess_content_type(path)
        return resp.status_code, resp.content, ctype
    except Exception as e:
        LOG.warning("httpx upstream failed for %s: %s", domain, e)
        return 502, f"Upstream fetch failed: {e}".encode("utf-8"), "text/plain"
    finally:
        if token is not None:
            _dns_overrides.reset(token)


# ---------------------------------------------------------------------------
# Backend proxy (async httpx)
# ---------------------------------------------------------------------------

async def _proxy_to_local_backend(domain: str, backend: dict, request: Request) -> Response:
    """Proxy request to a local HTTP backend (e.g., XAMPP Apache)."""
    origin = str(backend.get("origin") or "").strip().rstrip("/")
    if not origin:
        return Response(content="backend.origin missing", status_code=500, media_type="text/plain")
    if not _is_backend_origin_allowed(origin):
        msg = (
            f"backend.origin not allowed: {origin}\n"
            "Allowed hosts: 127.0.0.1, localhost, ::1 plus XAI_BACKEND_ALLOWLIST"
        )
        return Response(content=msg, status_code=403, media_type="text/plain")

    path = request.url.path
    query = str(request.url.query) if request.url.query else ""
    url = origin + path
    if query:
        url += f"?{query}"

    method = request.method.upper()
    body = None
    if method in ("POST", "PUT", "PATCH"):
        body = await request.body()

    headers: dict[str, str] = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP:
            continue
        if "\n" in v or "\r" in v:
            continue
        headers[k] = v

    headers["X-Forwarded-Proto"] = "https"
    headers["X-Forwarded-Host"] = domain
    headers["X-Forwarded-Port"] = "443"
    if request.client:
        headers["X-Forwarded-For"] = request.client.host

    timeout = float(backend.get("timeout") or 25.0)
    client = _get_http_client()

    try:
        resp = await client.request(
            method=method,
            url=url,
            headers=headers,
            content=body,
            timeout=timeout,
            follow_redirects=False,
        )
        resp_headers = {}
        for k, v in resp.headers.items():
            lk = k.lower()
            if lk in HOP_BY_HOP or lk == "content-length":
                continue
            resp_headers[k] = v

        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=resp_headers,
            media_type=resp.headers.get("content-type"),
        )
    except Exception as e:
        msg = (
            f"backend error: {e}\n\n"
            f"Configured backend.origin: {origin}\n"
            f"Fix: start that backend (XAMPP Apache/PHP) or update "
            f"server/websites/{domain}/directory.json backend.origin"
        )
        return Response(content=msg, status_code=502, media_type="text/plain")


# ---------------------------------------------------------------------------
# Backend probe
# ---------------------------------------------------------------------------

async def _probe_backend_http(origin: str, timeout: float = 4.0) -> dict:
    client = _get_http_client()
    try:
        resp = await client.get(origin, timeout=timeout)
        return {
            "ok": True,
            "status": resp.status_code,
            "contentType": resp.headers.get("content-type", ""),
        }
    except httpx.HTTPStatusError as e:
        return {"ok": False, "status": e.response.status_code, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _probe_backend_ws(origin: str, ws_path: str = "", timeout: float = 4.0) -> dict:
    if ws_create_connection is None:
        return {"ok": False, "error": "websocket-client not installed"}

    try:
        parsed = urllib.parse.urlparse(origin)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        base_path = parsed.path or ""
        path = ws_path or ""
        if path and not path.startswith("/"):
            path = "/" + path
        target = f"{ws_scheme}://{parsed.netloc}{base_path}{path}"
        c = ws_create_connection(target, timeout=timeout, enable_multithread=True)
        try:
            c.close()
        except Exception:
            pass
        return {"ok": True, "target": target}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Hosts management (unchanged from v2)
# ---------------------------------------------------------------------------

def _hosts_mapped_to_localhost(domain: str) -> bool:
    try:
        with open(HOSTS_PATH, "r", encoding="ascii", errors="ignore") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                ip = parts[0]
                names = [p for p in parts[1:] if not p.startswith("#")]
                if (ip == "127.0.0.1" or ip == "::1") and domain in names:
                    return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------------------
# GitHub sync
# ---------------------------------------------------------------------------

def _run_github_sync(args: list[str]) -> tuple[bool, str]:
    if not os.path.exists(GITHUB_SYNC_SCRIPT):
        return False, "github_sync.ps1 not found"
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        GITHUB_SYNC_SCRIPT,
    ] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    except Exception as e:
        return False, str(e)
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    if p.returncode != 0:
        msg = err or out or f"github_sync failed ({p.returncode})"
        return False, msg
    return True, out or "ok"


# ---------------------------------------------------------------------------
# Auto TLS cert regeneration
# ---------------------------------------------------------------------------

def _auto_regen_certs() -> Optional[str]:
    """Regenerate TLS certs if new domains are detected. Returns error string or None."""
    try:
        if not shutil.which("mkcert"):
            return "mkcert not found in PATH"

        domains_file = os.path.join(HERE, "domains.txt")
        # Scan website directories for domains
        current_domains = set()
        if os.path.isdir(BASE_DIR):
            for name in os.listdir(BASE_DIR):
                if os.path.isdir(os.path.join(BASE_DIR, name)):
                    current_domains.add(name.strip().lower())

        # Read existing domains.txt
        existing = set()
        if os.path.exists(domains_file):
            with open(domains_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        existing.add(line.lower())

        if not current_domains - existing:
            return None  # No new domains

        # Write updated domains.txt
        all_domains = sorted(existing | current_domains)
        with open(domains_file, "w", encoding="utf-8") as f:
            f.write("# Auto-generated by Domain Extension\n")
            for d in all_domains:
                f.write(d + "\n")

        # Regenerate certs
        cert_dir = os.path.join(HERE, "certs")
        os.makedirs(cert_dir, exist_ok=True)
        cmd = [
            "mkcert",
            "-cert-file", CERT_PATH,
            "-key-file", KEY_PATH,
        ] + all_domains
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if p.returncode != 0:
            return f"mkcert failed: {(p.stderr or p.stdout or '').strip()}"

        LOG.info("Auto-regenerated TLS certs for %d domains", len(all_domains))
        return None
    except Exception as e:
        return str(e)


# ---------------------------------------------------------------------------
# Auth check
# ---------------------------------------------------------------------------

def _check_ctrl_token(request: Request) -> Optional[JSONResponse]:
    if not CTRL_TOKEN:
        return None
    incoming = (request.headers.get("X-XAI-Token") or request.query_params.get("token") or "").strip()
    if incoming == CTRL_TOKEN:
        return None
    return JSONResponse({"error": "unauthorized"}, status_code=401)


# ---------------------------------------------------------------------------
# Apply header injection
# ---------------------------------------------------------------------------

def _apply_request_headers(headers: dict, header_config: dict) -> dict:
    """Apply request header modifications."""
    req_cfg = header_config.get("request", {})
    for k in req_cfg.get("remove", []):
        headers.pop(k, None)
        headers.pop(k.lower(), None)
    for k, v in req_cfg.get("set", {}).items():
        headers[k] = v
    return headers


def _apply_response_headers(response: Response, header_config: dict) -> Response:
    """Apply response header modifications."""
    res_cfg = header_config.get("response", {})
    for k, v in res_cfg.get("set", {}).items():
        response.headers[k] = v
    return response


# ---------------------------------------------------------------------------
# Mock response handler
# ---------------------------------------------------------------------------

def _handle_mock_route(route: dict) -> Response:
    """Return a mock response from route config."""
    status = int(route.get("status", 200))
    content_type = route.get("contentType", "application/json")
    body = route.get("body", {})
    if isinstance(body, (dict, list)):
        return Response(
            content=json.dumps(body, indent=2),
            status_code=status,
            media_type=content_type,
        )
    return Response(content=str(body), status_code=status, media_type=content_type)


# Alias for builtins.max to avoid conflict with query param name
builtins_max = max


# ---------------------------------------------------------------------------
# Control Plane App
# ---------------------------------------------------------------------------

def create_control_app() -> FastAPI:
    app = FastAPI(title="Domain Extension Control Plane", version=SERVER_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-XAI-Token"],
    )

    @app.api_route("/__xai/client-mode", methods=["GET", "POST", "OPTIONS"])
    async def set_client_mode_ctrl(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)

        domain = request.query_params.get("domain") or ""
        domain = domain.strip().lower()
        mode = request.query_params.get("mode") or ""
        mode = mode.strip().lower()

        if request.method == "POST":
            try:
                data = await request.json()
                if data:
                    domain = str(data.get("domain") or domain).strip().lower()
                    mode = str(data.get("mode") or mode).strip().lower()
            except Exception:
                pass

        if not domain:
            return JSONResponse({"error": "domain is required"}, status_code=400)

        client_ip = request.client.host if request.client else "127.0.0.1"
        _set_client_mode(client_ip, domain, mode)
        return JSONResponse({"ok": True, "clientIp": client_ip, "domain": domain, "mode": mode})

    @app.get("/__xai/client-overrides")
    async def get_client_overrides(request: Request):
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        with CLIENT_OVERRIDES_LOCK:
            return JSONResponse({"ok": True, "overrides": dict(CLIENT_OVERRIDES)})

    @app.api_route("/__xai/client-overrides", methods=["POST", "DELETE", "OPTIONS"])
    async def set_client_overrides_api(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied

        if request.method == "DELETE":
            client_ip = request.query_params.get("clientIp") or ""
            domain = request.query_params.get("domain") or ""
            client_ip = client_ip.strip()
            domain = domain.strip().lower()
            if not client_ip or not domain:
                try:
                    data = await request.json()
                    if data:
                        client_ip = str(data.get("clientIp") or client_ip).strip()
                        domain = str(data.get("domain") or domain).strip().lower()
                except Exception:
                    pass
            if not client_ip or not domain:
                return JSONResponse({"error": "clientIp and domain are required"}, status_code=400)
            
            _set_client_mode(client_ip, domain, "")
            return JSONResponse({"ok": True, "message": "Override cleared"})

        # POST method
        data = await request.json()
        client_ip = str(data.get("clientIp") or "").strip()
        domain = str(data.get("domain") or "").strip().lower()
        mode = str(data.get("mode") or "local").strip().lower()

        if not client_ip or not domain:
            return JSONResponse({"error": "clientIp and domain are required"}, status_code=400)
        if mode not in ("local", "proxy"):
            return JSONResponse({"error": "mode must be local or proxy"}, status_code=400)

        _set_client_mode(client_ip, domain, mode)
        return JSONResponse({"ok": True, "clientIp": client_ip, "domain": domain, "mode": mode})

    @app.get("/__xai/portal")
    async def portal_ctrl(request: Request, domain: str = ""):
        domain = domain.strip().lower()
        if not domain:
            return HTMLResponse(content="<h1>domain parameter is required</h1>", status_code=400)
        lan_ip = _get_lan_ip()
        content = PORTAL_HTML.replace("__DOMAIN__", domain).replace("__LAN_IP__", lan_ip)
        return HTMLResponse(content=content, status_code=200)

    @app.get("/__xai/ca")
    async def ca_download(request: Request):
        from fastapi.responses import FileResponse
        d = _get_ca_root_dir()
        if not d:
            return HTMLResponse(content="<h1>CA Directory Not Found</h1>", status_code=500)
        p = os.path.join(d, "rootCA.pem")
        if not os.path.isfile(p):
            return HTMLResponse(content="<h1>rootCA.pem File Not Found</h1>", status_code=404)
        return FileResponse(p, media_type="application/x-x509-ca-cert", filename="rootCA.pem")

    @app.get("/__xai/view/{domain}")
    @app.get("/__xai/view/{domain}/{path:path}")
    async def view_local_site(request: Request, domain: str, path: str = ""):
        domain = domain.strip().lower()
        if not _has_local_site(domain):
            return HTMLResponse(content=f"<h1>No local site found for {html.escape(domain)}</h1>", status_code=404)
        cfg = _read_site_config(domain)
        root = _site_root(domain)
        req_path = "/" + path.lstrip("/")
        is_html_main = False
        if req_path == "/":
            entry = cfg.get("entry") or "index.html"
            target = os.path.join(root, entry)
            is_html_main = True
        else:
            target = _safe_path(root, req_path)
            if not target:
                return HTMLResponse(content="<h1>Invalid path</h1>", status_code=400)
        if os.path.isdir(target):
            index_path = os.path.join(target, "index.html")
            if os.path.isfile(index_path):
                target = index_path
                is_html_main = True
            else:
                listing = _render_directory_listing(domain, target, f"/__xai/view/{domain}{req_path}")
                return HTMLResponse(content=listing, status_code=200)
        if os.path.exists(target) and os.path.isfile(target):
            ctype = _guess_content_type(target)
            with open(target, "rb") as f:
                body = f.read()
            if ctype.startswith("text/html"):
                body = _inject_toggle_gear(body)
            return Response(content=body, media_type=ctype)
        return HTMLResponse(content="<h1>File not found</h1>", status_code=404)

    @app.get("/__xai/status")



    async def status(request: Request, domain: str = ""):
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        domain = domain.strip().lower()
        if not domain:
            return JSONResponse({"error": "domain is required"}, status_code=400)

        mode = _default_mode(domain)
        return JSONResponse({
            "domain": domain,
            "mode": mode,
            "defaultMode": _default_mode(domain),
            "hasLocalSite": _has_local_site(domain),
            "isFakeTld": _is_fake_tld(domain),
            "hostsMapped": _hosts_mapped_to_localhost(domain),
            "hostsUpdated": False,
            "hostsError": None,
            "serverVersion": SERVER_VERSION,
            "lanIp": _get_lan_ip(),
        })

    @app.api_route("/__xai/mode", methods=["POST", "OPTIONS"])
    async def set_mode(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied

        data = await request.json()
        domain = str(data.get("domain") or "").strip().lower()
        mode = str(data.get("mode") or "").strip().lower()

        if not domain:
            return JSONResponse({"error": "domain is required"}, status_code=400)
        if mode not in ("local", "proxy"):
            return JSONResponse({"error": "mode must be local or proxy"}, status_code=400)
        if _is_fake_tld(domain) and mode != "local":
            return JSONResponse({"error": "fake TLDs are always local"}, status_code=400)

        return JSONResponse({
            "ok": True,
            "domain": domain,
            "mode": mode,
            "hostsUpdated": False,
            "hostsError": None,
            "hostsMapped": _hosts_mapped_to_localhost(domain),
            "note": "server-side overrides are disabled; switching is controlled by extension proxy routing",
        })
    @app.get("/__xai/metrics")
    async def metrics(request: Request, top: int = 20):
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        return JSONResponse(_metrics_snapshot(top_domains=top))

    @app.post("/__xai/metrics/reset")
    async def metrics_reset(request: Request):
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        global METRICS
        with METRICS_LOCK:
            METRICS["startedAt"] = time.time()
            METRICS["requestsTotal"] = 0
            METRICS["latencyMsTotal"] = 0.0
            METRICS["byMode"].clear()
            METRICS["statusClass"].clear()
            METRICS["domains"].clear()
            _log_entries.clear()
        return JSONResponse({"ok": True, "message": "metrics reset"})

    @app.get("/__xai/site-config")
    async def site_config_get(request: Request, domain: str = ""):
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        domain = domain.strip().lower()
        if not domain:
            return JSONResponse({"error": "domain is required"}, status_code=400)

        cfg = _read_site_config(domain)
        backend = cfg.get("backend")
        return JSONResponse({
            "domain": domain,
            "mode": cfg.get("mode", "local"),
            "entry": cfg["entry"],
            "backendOrigin": (backend or {}).get("origin"),
            "backendType": (backend or {}).get("type"),
            "backendProfile": (backend or {}).get("profile"),
            "backendHealthPath": (backend or {}).get("healthPath"),
            "backendWsPath": (backend or {}).get("wsPath"),
            "hasLocalSite": _has_local_site(domain),
            "latencyMs": cfg.get("latencyMs", 0),
            "watermark": cfg.get("watermark"),
            "headers": cfg.get("headers"),
            "routes": cfg.get("routes", []),
        })

    @app.api_route("/__xai/site-config", methods=["POST", "OPTIONS"])
    async def site_config_set(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        data = await request.json()
        domain = str(data.get("domain") or "").strip().lower()
        if not domain:
            return JSONResponse({"error": "domain is required"}, status_code=400)

        cfg_existing = _read_site_config(domain)
        backend_existing = cfg_existing.get("backend") or {}

        mode = str(data.get("mode") if "mode" in data else cfg_existing.get("mode") or "local").strip().lower()
        entry = str(data.get("entry") if "entry" in data else cfg_existing.get("entry") or "index.html").strip()

        backend_origin_raw = data.get("backendOrigin")
        if backend_origin_raw is not None:
            backend_origin = str(backend_origin_raw).strip()
        else:
            backend_origin = backend_existing.get("origin") or ""

        backend_type = str(data.get("backendType") if "backendType" in data else backend_existing.get("type") or "").strip()
        backend_profile = str(data.get("backendProfile") if "backendProfile" in data else backend_existing.get("profile") or "").strip()
        backend_health_path = str(data.get("backendHealthPath") if "backendHealthPath" in data else backend_existing.get("healthPath") or "").strip()
        backend_ws_path = str(data.get("backendWsPath") if "backendWsPath" in data else backend_existing.get("wsPath") or "").strip()

        if backend_origin and not _is_backend_origin_allowed(backend_origin):
            return JSONResponse({"error": "backendOrigin is not allowed"}, status_code=400)

        cfg = _write_site_config(
            domain=domain,
            entry=entry,
            backend_origin=backend_origin,
            backend_type=backend_type,
            backend_profile=backend_profile,
            backend_health_path=backend_health_path,
            backend_ws_path=backend_ws_path,
            mode=mode,
        )


        # Auto-regenerate TLS certs if new domain
        cert_err = _auto_regen_certs()
        if cert_err:
            LOG.warning("Auto cert regen: %s", cert_err)

        return JSONResponse({"ok": True, "domain": domain, "config": cfg})

    @app.get("/__xai/backend-profiles")
    async def backend_profiles(request: Request):
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        return JSONResponse({"profiles": BACKEND_PROFILES})

    @app.get("/__xai/backend-probe")
    async def backend_probe(request: Request, domain: str = "", wsPath: str = "", timeout: float = 4.0):
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        domain = domain.strip().lower()
        if not domain:
            return JSONResponse({"error": "domain is required"}, status_code=400)
        timeout = max(0.5, min(timeout, 20.0))

        cfg = _read_site_config(domain)
        backend = cfg.get("backend")
        if not backend or not str(backend.get("origin") or "").strip():
            return JSONResponse({"error": "backendOrigin is not set for domain"}, status_code=400)

        origin = str(backend.get("origin") or "").strip()
        allowed = _is_backend_origin_allowed(origin)
        out = {
            "domain": domain,
            "backendOrigin": origin,
            "allowed": allowed,
            "http": {"ok": False, "error": "skipped"},
            "ws": {"ok": False, "error": "skipped"},
        }
        if not allowed:
            out["error"] = "backendOrigin is not allowed"
            return JSONResponse(out, status_code=400)

        ws_path = wsPath or str(backend.get("wsPath") or "").strip()
        health_path = str(backend.get("healthPath") or "").strip()
        http_origin = origin
        if health_path:
            http_origin = origin.rstrip("/") + (health_path if health_path.startswith("/") else "/" + health_path)
        out["http"] = await _probe_backend_http(http_origin, timeout=timeout)
        out["ws"] = _probe_backend_ws(origin, ws_path=ws_path, timeout=timeout)
        return JSONResponse(out)

    @app.get("/__xai/health")
    async def health(request: Request, domains: str = "", wsPath: str = "", max: int = 50):
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        max_n = min(200, builtins_max(1, max))

        if domains:
            domain_list = sorted(set([d.strip() for d in domains.split(",") if d.strip()]))[:max_n]
        else:
            domain_list = _list_local_domains()[:max_n]

        items = []
        for d in domain_list:
            cfg = _read_site_config(d)
            backend = cfg.get("backend")
            backend_origin = (backend or {}).get("origin")
            item = {
                "domain": d,
                "hasLocalSite": _has_local_site(d),
                "defaultMode": _default_mode(d),
                "entry": cfg["entry"],
                "backendOrigin": backend_origin,
                "backendAllowed": bool(backend_origin and _is_backend_origin_allowed(str(backend_origin))),
            }
            if backend_origin and item["backendAllowed"]:
                hp = str((backend or {}).get("healthPath") or "").strip()
                wsp = wsPath or str((backend or {}).get("wsPath") or "").strip()
                http_origin = str(backend_origin)
                if hp:
                    http_origin = http_origin.rstrip("/") + (hp if hp.startswith("/") else "/" + hp)
                item["http"] = await _probe_backend_http(http_origin, timeout=2.5)
                item["ws"] = _probe_backend_ws(str(backend_origin), ws_path=wsp, timeout=2.5)
            items.append(item)

        return JSONResponse({
            "serverVersion": SERVER_VERSION,
            "count": len(items),
            "items": items,
        })

    # --- GitHub endpoints ---

    @app.get("/__xai/github/list")
    async def github_list(request: Request):
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        ok, out = _run_github_sync(["list"])
        if not ok:
            return JSONResponse({"error": out}, status_code=500)
        return JSONResponse({"ok": True, "output": out})

    @app.get("/__xai/github/status")
    async def github_status(request: Request):
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        ok, out = _run_github_sync(["status"])
        if not ok:
            return JSONResponse({"error": out}, status_code=500)
        return JSONResponse({"ok": True, "output": out})

    @app.api_route("/__xai/github/add", methods=["POST", "OPTIONS"])
    async def github_add(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        data = await request.json()
        domain = str(data.get("domain") or "").strip().lower()
        repo = str(data.get("repoUrl") or "").strip()
        branch = str(data.get("branch") or "main").strip() or "main"
        if not domain or not repo:
            return JSONResponse({"error": "domain and repoUrl are required"}, status_code=400)
        ok, out = _run_github_sync(["add", domain, repo, branch])
        if not ok:
            return JSONResponse({"error": out}, status_code=500)
        return JSONResponse({"ok": True, "output": out})

    @app.api_route("/__xai/github/pull", methods=["POST", "OPTIONS"])
    async def github_pull(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        data = await request.json()
        domain = str(data.get("domain") or "").strip().lower()
        if not domain:
            return JSONResponse({"error": "domain is required"}, status_code=400)
        ok, out = _run_github_sync(["pull", domain])
        if not ok:
            return JSONResponse({"error": out}, status_code=500)
        return JSONResponse({"ok": True, "output": out})

    @app.api_route("/__xai/github/pull-all", methods=["POST", "OPTIONS"])
    async def github_pull_all(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        ok, out = _run_github_sync(["pull-all"])
        if not ok:
            return JSONResponse({"error": out}, status_code=500)
        return JSONResponse({"ok": True, "output": out})

    @app.api_route("/__xai/github/remove", methods=["POST", "OPTIONS"])
    async def github_remove(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        data = await request.json()
        domain = str(data.get("domain") or "").strip().lower()
        keep_files = bool(data.get("keepFiles"))
        if not domain:
            return JSONResponse({"error": "domain is required"}, status_code=400)
        args = ["remove", domain]
        if keep_files:
            args.append("-KeepFiles")
        ok, out = _run_github_sync(args)
        if not ok:
            return JSONResponse({"error": out}, status_code=500)
        return JSONResponse({"ok": True, "output": out})

    # --- Live request log streaming (SSE) ---

    @app.get("/__xai/stream-logs")
    async def stream_logs(request: Request):
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied

        async def event_generator():
            last_index = len(_log_entries)
            while True:
                if last_index < len(_log_entries):
                    for entry in list(_log_entries)[last_index:]:
                        yield f"data: {json.dumps(entry)}\n\n"
                    last_index = len(_log_entries)
                await asyncio.sleep(0.5)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get("/__xai/logs")
    async def get_logs(request: Request, limit: int = 100):
        denied = _check_ctrl_token(request)
        if denied is not None:
            return denied
        limit_n = min(500, max(1, limit))
        return JSONResponse({
            "logs": list(_log_entries)[-limit_n:]
        })

    # --- Dynamic PAC file for network devices ---

    @app.get("/__xai/proxy.pac")
    async def get_pac_file(request: Request):
        host_header = request.headers.get("host", "")
        proxy_ip = "127.0.0.1"
        if host_header:
            proxy_ip = host_header.split(":", 1)[0]
        
        domains = _list_local_domains()
        exact_checks = " || ".join([f'host === "{d}"' for d in domains]) or "false"
        fake_checks = " || ".join([f'shExpMatch(host, "*{tld}")' for tld in FAKE_TLDS]) or "false"
        
        pac = f"""function FindProxyForURL(url, host) {{
  host = (host || "").toLowerCase();
  
  // Proxy fake TLDs
  if ({fake_checks}) return "PROXY {proxy_ip}:9081";
  
  // Proxy registered local domains
  if ({exact_checks}) return "PROXY {proxy_ip}:9081";
  
  return "DIRECT";
}}"""
        return Response(content=pac, media_type="application/x-ns-proxy-autoconfig")

    return app



PORTAL_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Domain Extension – Mobile Portal</title>
    <style>
        body {
            margin: 0; background: #030712; color: #f9fafb;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh; padding: 20px; box-sizing: border-box;
        }
        .card {
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid #1f2937;
            border-radius: 16px;
            padding: 36px 28px;
            max-width: 440px; width: 100%;
            text-align: center;
            box-shadow: 0 20px 40px rgba(0,0,0,0.6);
            backdrop-filter: blur(12px);
        }
        .logo { font-size: 26px; font-weight: 800; color: #6366f1; margin-bottom: 8px; letter-spacing: -0.5px; }
        .description { font-size: 14px; color: #9ca3af; margin-bottom: 24px; line-height: 1.5; }
        .domain-box {
            background: #090d16;
            border: 1px dashed #374151;
            border-radius: 8px;
            padding: 12px;
            font-family: monospace;
            font-size: 16px;
            color: #fbbf24;
            margin-bottom: 32px;
            word-break: break-all;
        }
        .btn-group { display: flex; flex-direction: column; gap: 14px; }
        button {
            padding: 16px 20px; font-size: 15px; font-weight: 700; border-radius: 8px; cursor: pointer; border: 1px solid transparent; transition: all 0.2s;
            outline: none;
        }
        .btn-local { background: #6366f1; color: #ffffff; box-shadow: 0 4px 14px rgba(99, 102, 241, 0.4); }
        .btn-local:hover { background: #4f46e5; }
        .btn-original { background: #1f2937; color: #f9fafb; border-color: #374151; }
        .btn-original:hover { background: #374151; }
        .footer { font-size: 11px; color: #4b5563; margin-top: 36px; }
    </style>
    <script>
        function setMode(mode) {
            try {
                var domain = "__DOMAIN__";
                var isControlPlane = window.location.pathname.indexOf("/__xai/") === 0 || window.location.port === "9080";
                var url = isControlPlane 
                    ? "/__xai/client-mode?domain=" + encodeURIComponent(domain) + "&mode=" + mode
                    : "/___xai/client-mode?mode=" + mode;

                var card = document.querySelector('.card');
                if (mode === 'proxy') {
                    card.innerHTML = '<div class="logo">🌐 Bypass Activated</div>' +
                        '<div class="description" style="color:#fcd34d;font-weight:600;margin-bottom:20px">' +
                        'Bypass registered successfully!</div>' +
                        '<div style="text-align:left;font-size:13px;line-height:1.6;color:#d1d5db;background:#090d16;border:1px solid #374151;border-radius:8px;padding:16px;margin-bottom:24px">' +
                        '<strong>⚠️ Critical step for mobile phones:</strong><br>' +
                        'Your phone browser caches DNS. To clear it and load the live site:<br>' +
                        '1. Toggle your phone\\\'s <strong>Wi-Fi Off and On</strong> (or turn on Airplane Mode for 5 seconds).<br>' +
                        '2. Relaunch your browser and open the site.' +
                        '</div>' +
                        '<button class="btn-original" onclick="window.location.reload()" style="width:100%">I have done this (Reload)</button>';
                }
                fetch(url)
                    .then(function(res) {
                        if (!res.ok) {
                            throw new Error("HTTP error! Status: " + res.status);
                        }
                        if (mode === 'local') {
                            if (isControlPlane) {
                                var lanIp = "__LAN_IP__";
                                window.location.href = "http://" + lanIp + ":9080/__xai/view/" + domain;
                            } else {
                                window.location.href = "https://" + domain;
                            }
                        } else {
                            window.location.href = "https://" + domain;
                        }
                    })
                    .catch(function(err) {
                        var debugBox = document.getElementById("debug-box");
                        if (!debugBox) {
                            debugBox = document.createElement("div");
                            debugBox.id = "debug-box";
                            debugBox.style.cssText = "color:#ef4444;font-size:12px;margin-top:16px;text-align:left;word-break:break-all;background:rgba(239,68,68,0.1);padding:10px;border-radius:6px;border:1px solid rgba(239,68,68,0.2)";
                            card.appendChild(debugBox);
                        }
                        debugBox.innerHTML = "<strong>Error:</strong> " + err.message;
                        var d = new Date();
                        d.setTime(d.getTime() + (7*24*60*60*1000));
                        document.cookie = "xai_mode=" + mode + ";path=/;expires=" + d.toGMTString();
                        
                        var lanIp = "__LAN_IP__";
                        var targetUrl = (mode === 'local' && isControlPlane)
                            ? "http://" + lanIp + ":9080/__xai/view/" + domain
                            : "https://" + domain;
                        setTimeout(function() { window.location.href = targetUrl; }, 2500);
                    });
            } catch (globalErr) {
                alert("JS Error: " + globalErr.message);
            }
        }
    </script>
</head>
<body>
    <div class="card">
        <div class="logo">🚀 Domain Extension</div>
        <div class="description">You are visiting a domain configured for local development on this network:</div>
        <div class="domain-box">__DOMAIN__</div>
        <div class="btn-group">
            <button class="btn-local" onclick="setMode('local')">🚀 Serve Local Development Version</button>
            <button class="btn-original" onclick="setMode('proxy')">🌐 Bypass to Original Live Version</button>
        </div>
        <div style="font-size:12.5px;color:#9ca3af;margin-top:20px;border-top:1px solid #1f2937;padding-top:14px;line-height:1.6;text-align:left">
            <strong>🔒 Trust HTTPS local pages on phone:</strong><br/>
            1. Open <a href="http://__LAN_IP__:9080/__xai/ca" style="color:#10b981;text-decoration:none;font-weight:700">http://__LAN_IP__:9080/__xai/ca</a> to download certificate.<br/>
            2. Install it in your settings as a trusted CA.<br/>
            <hr style="border:none;border-top:1px solid #1f2937;margin:8px 0"/>
            <strong>Blocked by HSTS?</strong> Open on phone:<br/>
            <a href="http://__LAN_IP__:9080/__xai/portal?domain=__DOMAIN__" style="color:#6366f1;text-decoration:none;font-weight:600">http://__LAN_IP__:9080/__xai/portal</a>
        </div>
        <div class="footer">Powered by Antigravity Domain Extension v3.0</div>
    </div>
</body>
</html>
"""

TOGGLE_GEAR_HTML = """
<div id="xai-toggle-gear" style="position:fixed; bottom:16px; right:16px; z-index:2147483647; background:#0b0f19; border:2px solid #6366f1; border-radius:50%; width:44px; height:44px; display:flex; align-items:center; justify-content:center; cursor:pointer; box-shadow:0 6px 20px rgba(0,0,0,0.6); transition: all 0.2s;" onclick="fetch('/___xai/client-mode?mode=').then(function(){document.cookie='xai_mode=;path=/;expires=Thu, 01 Jan 1970 00:00:00 UTC';window.location.reload();}).catch(function(){document.cookie='xai_mode=;path=/;expires=Thu, 01 Jan 1970 00:00:00 UTC';window.location.reload();});" onmouseover="this.style.transform='scale(1.1)';" onmouseout="this.style.transform='scale(1.0)';">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
</div>
"""


def _inject_toggle_gear(body: bytes) -> bytes:
    try:
        html_str = body.decode("utf-8", errors="ignore")
        if "</body>" in html_str:
            parts = html_str.rsplit("</body>", 1)
            html_str = parts[0] + TOGGLE_GEAR_HTML + "</body>" + parts[1]
        else:
            html_str += TOGGLE_GEAR_HTML
        return html_str.encode("utf-8", errors="ignore")
    except Exception:
        return body


# ---------------------------------------------------------------------------
# Main HTTPS Vhost App
# ---------------------------------------------------------------------------

def create_main_app() -> FastAPI:
    app = FastAPI(title="Domain Extension HTTPS Vhost", version=SERVER_VERSION)

    @app.get("/__xai/whoami")
    async def whoami(request: Request):
        domain = _domain_from_host(request.headers.get("host", ""))
        mode = _default_mode(domain)
        return JSONResponse({
            "domain": domain,
            "mode": mode,
            "hostsMapped": _hosts_mapped_to_localhost(domain),
            "hasLocalSite": _has_local_site(domain),
            "serverVersion": SERVER_VERSION,
        })

    @app.api_route(
        "/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def handle(request: Request, path: str = ""):
        t0 = time.perf_counter()
        domain = _domain_from_host(request.headers.get("host", ""))
        if not domain:
            return Response(content="Missing Host", status_code=400, media_type="text/plain")

        req_path = request.url.path or "/"

        # 1. Direct Portal Access
        if req_path == "/___xai/portal":
            lan_ip = _get_lan_ip()
            content = PORTAL_HTML.replace("__DOMAIN__", domain).replace("__LAN_IP__", lan_ip)
            return HTMLResponse(content=content, status_code=200)

        # 1.5. Client Mode Setting
        if req_path == "/___xai/client-mode":
            mode_param = request.query_params.get("mode", "").strip().lower()
            client_ip = request.client.host if request.client else "127.0.0.1"
            _set_client_mode(client_ip, domain, mode_param)
            
            response = JSONResponse({"ok": True, "clientIp": client_ip, "domain": domain, "mode": mode_param})
            if mode_param in ("local", "proxy"):
                response.set_cookie("xai_mode", mode_param, max_age=7*24*60*60, path="/")
            else:
                response.delete_cookie("xai_mode", path="/")
            return response

        # 2. Check Overrides (for real domains only)
        mode = _default_mode(domain)
        if not _is_fake_tld(domain) and _has_local_site(domain):
            client_ip = request.client.host if request.client else None
            client_mode = _get_client_mode(client_ip, domain) if client_ip else None
            cookie_mode = request.cookies.get("xai_mode")
            
            if client_mode in ("local", "proxy"):
                mode = client_mode
            elif cookie_mode in ("local", "proxy"):
                mode = cookie_mode
            else:
                # Intercept HTML requests to show portal
                is_html_request = "text/html" in request.headers.get("accept", "") or req_path == "/"
                if is_html_request:
                    lan_ip = _get_lan_ip()
                    content = PORTAL_HTML.replace("__DOMAIN__", domain).replace("__LAN_IP__", lan_ip)
                    return HTMLResponse(content=content, status_code=200)



        cfg = _read_site_config(domain)

        # Latency simulation
        latency_ms_config = cfg.get("latencyMs", 0)
        if latency_ms_config > 0:
            await asyncio.sleep(latency_ms_config / 1000.0)

        # Check path-based routes first
        matched_route = _match_route(cfg.get("routes", []), req_path)
        if matched_route:
            action = matched_route.get("action", "")

            if action == "mock":
                resp = _handle_mock_route(matched_route)
                resp = _apply_response_headers(resp, cfg.get("headers", {}))
                resp = _tag_response(resp, domain, mode)
                _finish_request(domain, mode, resp.status_code, t0)
                return resp

            if action == "proxy":
                target_origin = str(matched_route.get("target", "")).strip().rstrip("/")
                if target_origin and _is_backend_origin_allowed(target_origin):
                    route_backend = {"origin": target_origin, "timeout": 25.0}
                    resp = await _proxy_to_local_backend(domain, route_backend, request)
                    resp = _apply_response_headers(resp, cfg.get("headers", {}))
                    resp = _tag_response(resp, domain, mode)
                    _finish_request(domain, mode, resp.status_code, t0)
                    return resp

            if action == "static":
                target_dir = str(matched_route.get("target", ".")).strip()
                root = _site_root(domain)
                static_root = os.path.normpath(os.path.join(root, target_dir))
                # Strip the matched prefix from the path
                pattern = matched_route.get("path", "")
                prefix = pattern.rstrip("/*")
                sub_path = req_path[len(prefix):].lstrip("/") if req_path.startswith(prefix) else req_path.lstrip("/")
                file_path = _safe_path(static_root, "/" + sub_path) if sub_path else static_root
                if file_path and os.path.isfile(file_path):
                    ctype = _guess_content_type(file_path)
                    with open(file_path, "rb") as f:
                        body = f.read()
                    if ctype.startswith("text/html"):
                        body = _inject_toggle_gear(body)
                    resp = Response(content=body, media_type=ctype)
                    resp = _apply_response_headers(resp, cfg.get("headers", {}))
                    resp = _tag_response(resp, domain, mode)
                    _finish_request(domain, mode, resp.status_code, t0)
                    return resp

        # Standard mode handling
        if mode == "local":
            root = _site_root(domain)
            backend = cfg.get("backend")

            # If a backend is configured, proxy the whole site to it
            if backend:
                resp = await _proxy_to_local_backend(domain, backend, request)
                resp = _apply_response_headers(resp, cfg.get("headers", {}))
                # Watermark injection and toggle gear for HTML
                ctype = resp.headers.get("content-type", "")
                if "text/html" in ctype:
                    body = resp.body if hasattr(resp, "body") else b""
                    body = _inject_watermark(body, cfg.get("watermark", {}))
                    body = _inject_toggle_gear(body)
                    headers = dict(resp.headers)
                    headers.pop("content-length", None)
                    resp = Response(content=body, status_code=resp.status_code, media_type=ctype,
                                    headers=headers)
                resp = _tag_response(_maybe_add_local_headers(resp, domain, is_html_main=(req_path == "/")), domain, mode)
                _finish_request(domain, mode, resp.status_code, t0)
                return resp

            # Legacy path rewrite
            file_req_path = req_path
            if file_req_path.startswith("/Webpage/"):
                file_req_path = "/" + file_req_path[len("/Webpage/"):]

            is_html_main = False
            if file_req_path == "/":
                entry = cfg["entry"]
                target = os.path.join(root, entry)
                is_html_main = True
            else:
                target = _safe_path(root, file_req_path)
                if not target:
                    return Response(content="Invalid path", status_code=400, media_type="text/plain")

            if os.path.isdir(target):
                # Check for index.html in directory
                index_path = os.path.join(target, "index.html")
                if os.path.isfile(index_path):
                    target = index_path
                    is_html_main = True
                else:
                    # Styled directory explorer
                    listing = _render_directory_listing(domain, target, req_path)
                    resp = HTMLResponse(content=listing, status_code=200)
                    resp = _apply_response_headers(resp, cfg.get("headers", {}))
                    resp = _tag_response(_maybe_add_local_headers(resp, domain, is_html_main=True), domain, mode)
                    _finish_request(domain, mode, resp.status_code, t0)
                    return resp

            if os.path.exists(target) and os.path.isfile(target):
                ctype = _guess_content_type(target)
                with open(target, "rb") as f:
                    body = f.read()
                if ctype.startswith("text/html"):
                    if is_html_main:
                        body = _inject_watermark(body, cfg.get("watermark", {}))
                    body = _inject_toggle_gear(body)
                resp = Response(content=body, media_type=ctype)
                resp = _apply_response_headers(resp, cfg.get("headers", {}))
                resp = _tag_response(_maybe_add_local_headers(resp, domain, is_html_main), domain, mode)
                _finish_request(domain, mode, resp.status_code, t0)
                return resp

            # Missing entry file
            if is_html_main and _has_local_site(domain):
                entry = cfg["entry"]
                if os.path.basename(target).lower() == os.path.basename(entry).lower():
                    # Show directory explorer instead of bland error
                    listing = _render_directory_listing(domain, root, "/")
                    resp = HTMLResponse(content=listing, status_code=200)
                    resp = _apply_response_headers(resp, cfg.get("headers", {}))
                    resp = _tag_response(_maybe_add_local_headers(resp, domain, is_html_main=True), domain, mode)
                    _finish_request(domain, mode, resp.status_code, t0)
                    return resp

            # Fallback to upstream
            code, body, ctype = await _upstream_fetch(domain, request)
            resp = Response(content=body, status_code=code, media_type=ctype)
            if "text/html" in ctype:
                headers = dict(resp.headers)
                headers.pop("content-length", None)
                resp = Response(content=_inject_toggle_gear(body), status_code=code, media_type=ctype, headers=headers)
            resp = _apply_response_headers(resp, cfg.get("headers", {}))
            resp = _tag_response(_maybe_add_local_headers(resp, domain, is_html_main=(req_path == "/")), domain, mode)
            _finish_request(domain, mode, resp.status_code, t0)
            return resp

        # Proxy mode – fetch upstream
        code, body, ctype = await _upstream_fetch(domain, request)
        resp = Response(content=body, status_code=code, media_type=ctype)
        if "text/html" in ctype:
            headers = dict(resp.headers)
            headers.pop("content-length", None)
            resp = Response(content=_inject_toggle_gear(body), status_code=code, media_type=ctype, headers=headers)
        resp = _tag_response(resp, domain, mode)
        _finish_request(domain, mode, resp.status_code, t0)
        return resp

    return app


def _tag_response(resp: Response, domain: str, mode: str) -> Response:
    resp.headers["X-XAI-Version"] = SERVER_VERSION
    resp.headers["X-XAI-Domain"] = domain
    resp.headers["X-XAI-Mode"] = mode
    return resp


def _maybe_add_local_headers(resp: Response, domain: str, is_html_main: bool) -> Response:
    resp.headers["Cache-Control"] = "no-store"
    if DEFAULT_CLEAR_SITE_DATA and (not _is_fake_tld(domain)) and is_html_main:
        resp.headers["Clear-Site-Data"] = '"cache", "storage", "executionContexts"'
    return resp


def _finish_request(domain: str, mode: str, status_code: int, t0: float) -> None:
    latency_ms = (time.perf_counter() - t0) * 1000.0
    _record_metric(domain=domain, mode=mode, status_code=status_code, latency_ms=latency_ms)
    _push_log_entry({
        "ts": int(time.time() * 1000),
        "domain": domain,
        "mode": mode,
        "status": status_code,
        "latencyMs": round(latency_ms, 1),
    })
    LOG.info(
        "req domain=%s mode=%s status=%s latency_ms=%.1f",
        domain, mode, status_code, latency_ms,
    )


# ---------------------------------------------------------------------------
# CONNECT Proxy (raw TCP – unchanged from v2)
# ---------------------------------------------------------------------------

def _start_connect_proxy(proxy_host: str, proxy_port: int, https_port: int) -> None:
    class _ProxyHandler(socketserver.StreamRequestHandler):
        def _connect_upstream(self, host: str, port: int) -> socket.socket:
            client_ip = self.client_address[0] if self.client_address else None
            if _should_intercept_dns(host, client_ip=client_ip):

                last: Optional[Exception] = None
                for addr in [("127.0.0.1", https_port), ("::1", https_port)]:
                    try:
                        return socket.create_connection(addr, timeout=5)
                    except Exception as e:
                        last = e
                        continue
                raise last or RuntimeError("failed to connect to local https")
            else:
                try:
                    return socket.create_connection((host, port), timeout=8)
                except Exception as e:
                    raise RuntimeError(f"failed to connect to upstream {host}:{port} - {e}")

        def _relay(self, a: socket.socket, b: socket.socket) -> None:
            a.setblocking(False)
            b.setblocking(False)
            sockets = [a, b]
            while True:
                r, _w, _x = select.select(sockets, [], [], 60)
                if not r:
                    continue
                for s in r:
                    try:
                        data = s.recv(65536)
                    except Exception:
                        return
                    if not data:
                        return
                    other = b if s is a else a
                    try:
                        other.sendall(data)
                    except Exception:
                        return

        def handle(self) -> None:
            try:
                first = self.rfile.readline(65536)
                if not first:
                    return
                try:
                    line = first.decode("iso-8859-1", errors="replace").strip()
                except Exception:
                    return
                parts = line.split()
                if len(parts) < 3:
                    return
                method = parts[0].upper()
                target = parts[1]

                # Drain headers.
                while True:
                    h = self.rfile.readline(65536)
                    if not h or h in (b"\r\n", b"\n"):
                        break

                if method != "CONNECT":
                    self.wfile.write(b"HTTP/1.1 501 Not Implemented\r\nConnection: close\r\n\r\nUse HTTPS (CONNECT)\r\n")
                    return

                # Parse destination host and port
                host_port = target.split(":", 1)
                host = host_port[0]
                port = 443
                if len(host_port) > 1:
                    try:
                        port = int(host_port[1])
                    except ValueError:
                        pass

                try:
                    upstream = self._connect_upstream(host, port)
                except Exception as e:
                    self.wfile.write(f"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\nError: {e}\r\n".encode("utf-8"))
                    return

                try:
                    self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    self.wfile.flush()
                    self._relay(self.connection, upstream)
                finally:
                    try:
                        upstream.close()
                    except Exception:
                        pass
            except Exception:
                return

    class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    try:
        proxy = _ThreadingTCPServer((proxy_host, proxy_port), _ProxyHandler)
        t_proxy = threading.Thread(target=proxy.serve_forever, daemon=True)
        t_proxy.start()
        LOG.info("PAC proxy: http://%s:%s (CONNECT tunnels to local HTTPS)", proxy_host, proxy_port)
    except Exception as e:
        LOG.error("Failed to start PAC proxy on %s:%s: %s", proxy_host, proxy_port, e)


# ---------------------------------------------------------------------------
# Server Startup
# ---------------------------------------------------------------------------

def _is_admin() -> bool:
    """Check if the current process has administrator/root privileges."""
    try:
        return ctypes.windll.kernel32.GetCurrentProcess() and ctypes.windll.shell32.IsUserAnAdmin() != 0  # type: ignore[attr-defined]
    except Exception:
        # Non-Windows or ctypes not available
        return os.getuid() == 0 if hasattr(os, "getuid") else False  # type: ignore[attr-defined]


def run_servers(control_host: str, control_port: int, https_host: str, https_port: int) -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

    os.makedirs(BASE_DIR, exist_ok=True)
    _load_client_overrides()


    # Detect LAN IP early
    lan_ip = _get_lan_ip()
    LOG.info("Detected LAN IP: %s", lan_ip)

    # Auto-regen certs on startup
    cert_err = _auto_regen_certs()
    if cert_err:
        LOG.warning("Cert auto-regen: %s", cert_err)

    ctrl_app = create_control_app()
    main_app = create_main_app()

    # Start control plane on a separate thread with uvicorn
    ctrl_config = uvicorn.Config(
        ctrl_app,
        host=control_host,
        port=control_port,
        log_level="info",
    )
    ctrl_server = uvicorn.Server(ctrl_config)
    t = threading.Thread(target=ctrl_server.run, daemon=True)
    t.start()
    LOG.info("Control plane: http://%s:%s", control_host, control_port)

    # Start LAN DNS server (requires admin for port 53)
    dns_host = os.environ.get("XAI_DNS_HOST", "0.0.0.0")
    dns_port = int(os.environ.get("XAI_DNS_PORT", "53"))
    dns_enabled = os.environ.get("XAI_DNS_ENABLED", "1").strip() not in ("0", "false", "False")

    if dns_enabled:
        is_unix = os.name != "nt"
        if dns_port == 53 and is_unix and not _is_admin():
            LOG.warning(
                "DNS server: port 53 requires root/Administrator privileges. "
                "Skipping DNS server. Run as root/Admin to enable LAN DNS, "
                "or set XAI_DNS_PORT to a non-privileged port (e.g. 5353)."
            )
        else:
            # Launch DNS in a background thread with its own event loop
            def _dns_thread() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                transport = loop.run_until_complete(_start_dns_server(dns_host, dns_port))
                if transport:
                    loop.run_forever()

            dns_t = threading.Thread(target=_dns_thread, daemon=True)
            dns_t.start()
    else:
        LOG.info("LAN DNS server disabled (XAI_DNS_ENABLED=0)")

    if not (os.path.exists(CERT_PATH) and os.path.exists(KEY_PATH)):
        LOG.error("Missing TLS cert/key. Generate them with: python manage.py certs --install")
        LOG.error("Expected cert: %s", CERT_PATH)
        LOG.error("Expected key : %s", KEY_PATH)
        LOG.error("Control plane is running, but HTTPS server will not start.")
        t.join()
        return

    # Start CONNECT proxy
    proxy_host = os.environ.get("XAI_PROXY_HOST", "0.0.0.0")
    proxy_port = int(os.environ.get("XAI_PROXY_PORT", "9081"))
    _start_connect_proxy(proxy_host, proxy_port, https_port)

    # Start HTTPS vhost with uvicorn
    https_config = uvicorn.Config(
        main_app,
        host=https_host,
        port=https_port,
        ssl_certfile=CERT_PATH,
        ssl_keyfile=KEY_PATH,
        log_level="info",
    )
    https_server = uvicorn.Server(https_config)
    LOG.info("HTTPS vhost: https://%s:%s", https_host, https_port)
    LOG.info("")
    LOG.info("=" * 60)
    LOG.info("  Domain Extension v%s - All services started", SERVER_VERSION)
    LOG.info("  LAN IP       : %s", lan_ip)
    LOG.info("  HTTPS        : https://%s:%s", https_host, https_port)
    LOG.info("  Control API  : http://%s:%s", control_host, control_port)
    LOG.info("  DNS          : %s (udp://%s:%s)", "active" if dns_enabled else "disabled", dns_host, dns_port)
    LOG.info("  CONNECT Proxy: http://%s:%s", proxy_host, proxy_port)
    LOG.info("=" * 60)
    LOG.info("")
    https_server.run()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--control-host", default="0.0.0.0")
    p.add_argument("--control-port", type=int, default=9080)
    p.add_argument("--https-host", default="0.0.0.0")
    p.add_argument("--https-port", type=int, default=443)
    args = p.parse_args()

    os.makedirs(BASE_DIR, exist_ok=True)
    run_servers(args.control_host, args.control_port, args.https_host, args.https_port)


if __name__ == "__main__":
    main()
