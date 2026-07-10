@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo.
echo == Domain Extension: Extract CA Certificate ==
echo.

where mkcert >nul 2>&1
if %errorlevel% neq 0 (
  echo [ERR] mkcert is not found in your PATH.
  echo       Please install mkcert first using scoop, winget, or by downloading the binary.
  pause
  exit /b 1
)

for /f "delims=" %%i in ('mkcert -CAROOT') do set "CAROOT=%%i"

if not exist "%CAROOT%\rootCA.pem" (
  echo [ERR] Root CA file not found in %CAROOT%.
  echo       Has mkcert been initialized? Try running: python manage.py certs --install
  pause
  exit /b 1
)

echo Found Root CA directory: %CAROOT%
echo Copying rootCA.pem to project root...
copy /y "%CAROOT%\rootCA.pem" "rootCA.pem" >nul

if %errorlevel% equ 0 (
  echo.
  echo [OK] Successfully copied rootCA.pem to the project folder.
  echo.
  echo How to install on your phone:
  echo ---------------------------------------------------------------------
  echo 1. Send the file "rootCA.pem" to your phone (Email, AirDrop, Google Drive, etc.).
  echo 2. On iOS:
  echo    - Open the downloaded file to add it as a profile.
  echo    - Go to Settings -> Profile Downloaded -> Install.
  echo    - Go to Settings -> General -> About -> Certificate Trust Settings.
  echo    - Enable full trust for "mkcert development CA".
  echo 3. On Android:
  echo    - Go to Settings -> Security -> Encryption & Credentials -> Install a Certificate.
  echo    - Choose "CA Certificate" and select "rootCA.pem".
  echo ---------------------------------------------------------------------
  echo.
  echo Opening folder...
  explorer.exe /select,rootCA.pem
) else (
  echo [ERR] Failed to copy the CA file.
)

endlocal
