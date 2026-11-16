@echo off
cd /d "%~dp0"
echo Comparing settings on your last recording... (1-3 minutes)
".venv\Scripts\python.exe" tools\diagnose.py
echo.
echo Done. Results saved to debug\diagnose.txt
