@echo off
setlocal EnableExtensions

REM Stop all Domain Extension processes and release ports.
REM Requires admin elevation.

cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo.
  echo [!] Administrator required. Re-launching elevated...
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0' -WorkingDirectory '%~dp0'"
  exit /b 0
)

echo.
echo == Domain Extension: STOP ==
echo.

echo [1/3] Stopping server processes via CLI...
python manage.py stop

echo.
echo [2/3] Cleaning up any remaining port listeners (443, 53, 9080, 9081)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :9080 ^| findstr LISTENING') do (
  echo   - Killing PID %%a on :9080
  taskkill /f /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :443 ^| findstr LISTENING') do (
  echo   - Killing PID %%a on :443
  taskkill /f /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :53 ^| findstr LISTENING') do (
  echo   - Killing PID %%a on :53
  taskkill /f /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :9081 ^| findstr LISTENING') do (
  echo   - Killing PID %%a on :9081
  taskkill /f /pid %%a >nul 2>&1
)

echo.
echo [3/3] Disabling hosts overrides...
if exist "server\hosts.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File server\hosts.ps1 disable
)

echo.
echo Done.
endlocal
