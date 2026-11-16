@echo off
REM Compares the new model with Ethio-ASR on your voice-profile recordings.
cd /d "%~dp0"
set MODEL=%~dp0models\final
if not exist "%MODEL%\config.json" (echo Put the unzipped model in models\final first & pause & exit /b 1)
".venv\Scripts\python.exe" tools\compare_models.py "%MODEL%" badrex/Ethio-ASR-amharic > compare_log.txt 2>&1
type compare_results.txt
pause
