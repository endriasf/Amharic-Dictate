@echo off
REM Stops Amharic Dictate and starts it again.
REM Note: ends all pythonw.exe processes (Amharic Dictate is normally the only one).
cd /d "%~dp0"
taskkill /F /T /IM pythonw.exe >/dev/null 2>&1
timeout /t 2 /nobreak >nul
start "" ".venv\Scripts\pythonw.exe" app.py
