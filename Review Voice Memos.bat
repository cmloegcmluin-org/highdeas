@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
".venv\Scripts\python.exe" -m voicememo.app
pause
