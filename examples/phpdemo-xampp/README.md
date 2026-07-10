# PHP Demo for XAMPP

This folder is an example dynamic PHP app for the domain `phpdemo.fake`.

## Quick setup

1. Copy this folder to your XAMPP web root:
   - From: `examples\phpdemo-xampp`
   - To: `C:\xampp\htdocs\phpdemo`
2. Start Apache in XAMPP (default port `80`).
3. Start Domain Extension server with `start_all.bat`.
4. Open `https://phpdemo.fake/`.

If Apache uses a different port, update:
- `server\websites\phpdemo.fake\directory.json`
  - `backend.origin` value.
