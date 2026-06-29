@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m flask --app app run --host 127.0.0.1 --port 5000 --no-reload
pause
