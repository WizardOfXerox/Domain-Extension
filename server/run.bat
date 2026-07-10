@echo off
setlocal
cd /d "%~dp0.."

echo Starting Domain Extension via manage.py...
python manage.py start %*
pause
