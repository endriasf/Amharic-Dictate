@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" tools\compare_models.py --dump decoder_tuning.npz "%~dp0models\final" > dump_log.txt 2>&1
