@echo off
setlocal
cd /d "%~dp0"

REM Root wrapper to start the Domain Extension server stack.
python manage.py start %*