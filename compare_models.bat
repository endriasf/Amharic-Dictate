@echo off
REM Unzips the new model (first time) and compares it with Ethio-ASR on your voice-profile recordings.
cd /d "%~dp0"
set MODEL=%~dp0models\final
echo Unzipping the model (one time, about a minute)...
if not exist models mkdir models
if exist MY_AMHARIC_MODEL.zip tar -xf MY_AMHARIC_MODEL.zip -C models
if not exist "%MODEL%\config.json" (echo Model not found in models\final & pause & exit /b 1)
echo Comparing models on your recordings (5-15 minutes). Please wait...
".venv\Scripts\python.exe" tools\compare_models.py "%MODEL%" badrex/Ethio-ASR-amharic > compare_log.txt 2>&1
echo.
type compare_results.txt
echo.
echo Finished. You can close this window.
pause
