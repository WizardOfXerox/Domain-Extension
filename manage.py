#!/usr/bin/env python3
"""Domain Extension – Unified cross-platform CLI.

Replaces the PowerShell scripts with Python equivalents that work on
Windows, macOS, and Linux.

Usage:
    python manage.py start               Start the server stack
    python manage.py stop                Stop all server processes
    python manage.py certs               Generate TLS certificates
    python manage.py certs --install     Install CA + generate certs
    python manage.py sync-domains        Sync website dirs to domains.txt
    python manage.py sync-domains --update-cert  Sync + regenerate cert
    python manage.py new-pack            Scaffold a new dev environment
    python manage.py status              Show current server status
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time

HERE = os.path.abspath(os.path.dirname(__file__))
SERVER_DIR = os.path.join(HERE, "server")
WEBSITES_DIR = os.path.join(SERVER_DIR, "websites")
DOMAINS_FILE = os.path.join(SERVER_DIR, "domains.txt")
CERT_PATH = os.path.join(SERVER_DIR, "certs", "cert.pem")
KEY_PATH = os.path.join(SERVER_DIR, "certs", "key.pem")
PACKS_DIR = os.path.join(SERVER_DIR, "packs")

SYSTEM = platform.system()  # "Windows", "Darwin", "Linux"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def info(msg: str) -> None:
    try:
        print(f"  [*] {msg}")
    except UnicodeEncodeError:
        print(f"  [*] {msg.encode('ascii', errors='replace').decode('ascii')}")


def success(msg: str) -> None:
    try:
        print(f"  [OK] {msg}")
    except UnicodeEncodeError:
        print(f"  [OK] {msg.encode('ascii', errors='replace').decode('ascii')}")


def warn(msg: str) -> None:
    try:
        print(f"  [!] {msg}")
    except UnicodeEncodeError:
        print(f"  [!] {msg.encode('ascii', errors='replace').decode('ascii')}")


def error(msg: str) -> None:
    try:
        print(f"  [ERR] {msg}")
    except UnicodeEncodeError:
        print(f"  [ERR] {msg.encode('ascii', errors='replace').decode('ascii')}")



def ensure_mkcert() -> bool:
    """Check if mkcert is available; if not, print OS-specific instructions."""
    if shutil.which("mkcert"):
        return True

    error("mkcert is not found in PATH.")
    print()
    if SYSTEM == "Windows":
        print("  Install with winget:")
        print("    winget install FiloSottile.mkcert")
        print()
        print("  Or download from: https://github.com/FiloSottile/mkcert/releases")
    elif SYSTEM == "Darwin":
        print("  Install with Homebrew:")
        print("    brew install mkcert")
        print("    brew install nss  # if you use Firefox")
    else:
        print("  Install on Ubuntu/Debian:")
        print("    sudo apt install mkcert libnss3-tools")
        print()
        print("  Install on Arch:")
        print("    sudo pacman -S mkcert")
        print()
        print("  Or download from: https://github.com/FiloSottile/mkcert/releases")
    print()
    return False


def get_website_domains() -> list[str]:
    """Scan server/websites/ for domain directories."""
    domains = []
    if not os.path.isdir(WEBSITES_DIR):
        return domains
    for name in sorted(os.listdir(WEBSITES_DIR)):
        full = os.path.join(WEBSITES_DIR, name)
        if os.path.isdir(full):
            domains.append(name.strip().lower())
    return sorted(set(d for d in domains if d))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_start(args: argparse.Namespace) -> None:
    """Start the Domain Extension server stack."""
    info("Starting Domain Extension server...")

    # Auto-sync domains and certs
    domains = get_website_domains()
    if domains:
        _write_domains_file(domains)
        if ensure_mkcert():
            _generate_certs(domains, install=False)

    app_path = os.path.join(SERVER_DIR, "app.py")
    if not os.path.exists(app_path):
        error(f"Server not found: {app_path}")
        return

    cmd = [sys.executable, app_path]
    if args.control_port:
        cmd += ["--control-port", str(args.control_port)]
    if args.https_port:
        cmd += ["--https-port", str(args.https_port)]

    info(f"Running: {' '.join(cmd)}")
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        info("Server stopped.")


def cmd_stop(args: argparse.Namespace) -> None:
    """Stop all Domain Extension server processes."""
    info("Stopping Domain Extension processes...")

    if SYSTEM == "Windows":
        # Find and kill python processes running app.py
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-Process python* -ErrorAction SilentlyContinue | "
                 "Where-Object { $_.CommandLine -like '*app.py*' } | "
                 "Stop-Process -Force"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
            )
            if result.returncode == 0:
                success("Stopped server processes.")
            else:
                warn("No running server processes found.")
        except Exception as e:
            warn(f"Stop failed: {e}")
    else:
        try:
            subprocess.run(
                ["pkill", "-f", "app.py"],
                capture_output=True, timeout=10
            )
            success("Sent kill signal to server processes.")
        except Exception:
            warn("pkill not available or no processes found.")


def cmd_certs(args: argparse.Namespace) -> None:
    """Generate TLS certificates using mkcert."""
    if not ensure_mkcert():
        sys.exit(1)

    domains = get_website_domains()
    if not domains:
        error("No website domains found. Create folders in server/websites/ first.")
        sys.exit(1)

    _write_domains_file(domains)

    if args.install:
        info("Installing local CA trust...")
        result = subprocess.run(["mkcert", "-install"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode == 0:
            success("CA installed successfully.")
        else:
            error(f"CA install failed: {result.stderr}")

    _generate_certs(domains, install=False)


def _write_domains_file(domains: list[str]) -> None:
    """Write the domains list to domains.txt."""
    with open(DOMAINS_FILE, "w", encoding="utf-8") as f:
        f.write("# Auto-generated by Domain Extension manage.py\n")
        for d in domains:
            f.write(d + "\n")
    info(f"Wrote {len(domains)} domains to {DOMAINS_FILE}")


def _generate_certs(domains: list[str], install: bool = False) -> None:
    """Run mkcert to generate cert.pem and key.pem."""
    cert_dir = os.path.dirname(CERT_PATH)
    os.makedirs(cert_dir, exist_ok=True)

    cmd = ["mkcert", "-cert-file", CERT_PATH, "-key-file", KEY_PATH] + domains
    info(f"Generating certs for {len(domains)} domains...")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode == 0:
        success(f"Wrote cert: {CERT_PATH}")
        success(f"Wrote key:  {KEY_PATH}")
    else:
        error(f"mkcert failed: {result.stderr}")


def cmd_sync_domains(args: argparse.Namespace) -> None:
    """Sync website directories into domains.txt."""
    domains = get_website_domains()
    if not domains:
        warn("No website domains found in server/websites/")
        return

    _write_domains_file(domains)
    success(f"Synced {len(domains)} domains.")

    if args.update_cert:
        if not ensure_mkcert():
            return
        _generate_certs(domains)


def cmd_new_pack(args: argparse.Namespace) -> None:
    """Scaffold a new dev environment from a template pack."""
    pack = args.pack
    domain = args.domain
    project = args.project or domain.split(".")[0]

    pack_dir = os.path.join(PACKS_DIR, pack)
    if not os.path.isdir(pack_dir):
        available = [d for d in os.listdir(PACKS_DIR) if os.path.isdir(os.path.join(PACKS_DIR, d))]
        error(f"Pack '{pack}' not found.")
        info(f"Available packs: {', '.join(available)}")
        sys.exit(1)

    # Default origin hints
    origin_hints = {
        "php-xampp": f"http://127.0.0.1/{project}",
        "node-express": "http://127.0.0.1:3000",
        "wordpress-xampp": "http://127.0.0.1/wordpress",
        "laravel": "http://127.0.0.1:8000",
        "nextjs": "http://127.0.0.1:3000",
        "vite-react": "http://127.0.0.1:5173",
        "django": "http://127.0.0.1:8000",
        "vue-vite": "http://127.0.0.1:5173",
    }
    origin = origin_hints.get(pack, "http://127.0.0.1:3000")


    # Token replacements
    tokens = {
        "__DOMAIN__": domain,
        "__PACK__": pack,
        "__ORIGIN__": origin,
        "__PROJECT__": project,
    }

    # Copy site template
    site_src = os.path.join(pack_dir, "site")
    site_dst = os.path.join(WEBSITES_DIR, domain)
    if os.path.isdir(site_src):
        os.makedirs(site_dst, exist_ok=True)
        _copy_with_tokens(site_src, site_dst, tokens)
        success(f"Site template -> {site_dst}")
    else:
        # Create minimal directory.json
        os.makedirs(site_dst, exist_ok=True)
        cfg = {"entry": "index.html", "backend": {"origin": origin, "type": pack.split("-")[0]}}
        with open(os.path.join(site_dst, "directory.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        success(f"Created minimal config -> {site_dst}")

    # Copy backend template
    backend_src = os.path.join(pack_dir, "backend")
    backend_dst = os.path.join(HERE, "examples", "generated", f"{domain}-{pack}")
    if os.path.isdir(backend_src):
        os.makedirs(backend_dst, exist_ok=True)
        _copy_with_tokens(backend_src, backend_dst, tokens)
        success(f"Backend template -> {backend_dst}")

    info(f"Pack '{pack}' scaffolded for {domain}.")


def _copy_with_tokens(src: str, dst: str, tokens: dict) -> None:
    """Recursively copy directory, replacing tokens in text files."""
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_dir = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(target_dir, exist_ok=True)
        for fname in files:
            src_file = os.path.join(root, fname)
            dst_file = os.path.join(target_dir, fname)
            try:
                with open(src_file, "r", encoding="utf-8") as f:
                    content = f.read()
                for token, value in tokens.items():
                    content = content.replace(token, value)
                with open(dst_file, "w", encoding="utf-8") as f:
                    f.write(content)
            except (UnicodeDecodeError, ValueError):
                # Binary file – copy as-is
                shutil.copy2(src_file, dst_file)


def cmd_status(args: argparse.Namespace) -> None:
    """Show current server status."""
    import urllib.request

    info("Checking server status...")
    try:
        with urllib.request.urlopen("http://127.0.0.1:9080/__xai/status?domain=test.fake", timeout=3) as resp:
            data = json.loads(resp.read())
            success(f"Server ONLINE (v{data.get('serverVersion', '?')})")
    except Exception:
        warn("Server appears OFFLINE.")

    domains = get_website_domains()
    info(f"Registered domains: {len(domains)}")
    for d in domains[:20]:
        print(f"    {d}")
    if len(domains) > 20:
        print(f"    ... and {len(domains) - 20} more")

    info(f"Cert exists: {os.path.exists(CERT_PATH)}")
    info(f"Key exists:  {os.path.exists(KEY_PATH)}")
    info(f"mkcert available: {bool(shutil.which('mkcert'))}")
    info(f"Platform: {SYSTEM} ({platform.machine()})")


# ---------------------------------------------------------------------------
# CLI Entry
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="manage",
        description="Domain Extension – Unified CLI",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # start
    p_start = sub.add_parser("start", help="Start the server stack")
    p_start.add_argument("--control-port", type=int, default=None)
    p_start.add_argument("--https-port", type=int, default=None)

    # stop
    sub.add_parser("stop", help="Stop all server processes")

    # certs
    p_certs = sub.add_parser("certs", help="Generate TLS certificates")
    p_certs.add_argument("--install", action="store_true", help="Install local CA trust first")

    # sync-domains
    p_sync = sub.add_parser("sync-domains", help="Sync website dirs -> domains.txt")
    p_sync.add_argument("--update-cert", action="store_true", help="Regenerate cert after sync")

    # new-pack
    p_pack = sub.add_parser("new-pack", help="Scaffold a dev environment from a template")
    p_pack.add_argument("--pack", required=True, help="Pack name (e.g., php-xampp, node-express, nextjs, vite-react)")
    p_pack.add_argument("--domain", required=True, help="Domain name (e.g., myapp.fake)")
    p_pack.add_argument("--project", default=None, help="Project name (defaults to domain prefix)")

    # status
    sub.add_parser("status", help="Show current server status")

    args = parser.parse_args()

    if args.command == "start":
        cmd_start(args)
    elif args.command == "stop":
        cmd_stop(args)
    elif args.command == "certs":
        cmd_certs(args)
    elif args.command == "sync-domains":
        cmd_sync_domains(args)
    elif args.command == "new-pack":
        cmd_new_pack(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
