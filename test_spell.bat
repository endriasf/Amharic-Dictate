@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" tools\test_wordspell.py > spell_test.txt 2>&1
echo FINISHED >> spell_test.txt
