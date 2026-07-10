@echo off
setlocal EnableExtensions

REM All-in-one setup and run.
REM Installs python dependencies and launches the server.

cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo.
  echo [!] Administrator required. Re-launching elevated...
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0' -WorkingDirectory '%~dp0..'"
  exit /b 0
)

echo.
echo == Domain Extension: Setup + Run ==
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
  echo [!] python not found in PATH.
  echo     Install Python 3 and make sure `python` is available.
  pause
  exit /b 1
)

echo [1/4] Installing Python dependencies...
python -m pip install -r server\requirements.txt
if %errorlevel% neq 0 (
  echo [!] pip install failed.
  pause
  exit /b 1
)

echo.
echo [2/4] Setting up Windows Firewall rules for LAN sharing...
powershell -NoProfile -ExecutionPolicy Bypass -Command "New-NetFirewallRule -DisplayName 'Domain Extension DNS' -Direction Inbound -LocalPort 53 -Protocol UDP -Action Allow -ErrorAction SilentlyContinue | Out-Null"
powershell -NoProfile -ExecutionPolicy Bypass -Command "New-NetFirewallRule -DisplayName 'Domain Extension HTTPS' -Direction Inbound -LocalPort 443 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue | Out-Null"
powershell -NoProfile -ExecutionPolicy Bypass -Command "New-NetFirewallRule -DisplayName 'Domain Extension Control' -Direction Inbound -LocalPort 9080 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue | Out-Null"
powershell -NoProfile -ExecutionPolicy Bypass -Command "New-NetFirewallRule -DisplayName 'Domain Extension Proxy' -Direction Inbound -LocalPort 9081 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue | Out-Null"
echo   [OK] Inbound firewall rules applied.

echo.
echo [3/4] Checking certifications...
python manage.py certs

echo.
echo [4/4] Launching Domain Extension...
python manage.py start %*

endlocal
