@echo off
REM One-time setup. Requires Python 3.11 or 3.12 (python.org, tick "Add to PATH").
cd /d "%~dp0"
python -m venv .venv || goto :error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
REM CPU build of PyTorch. For an NVIDIA GPU, replace the index URL with
REM https://download.pytorch.org/whl/cu124
pip install torch --index-url https://download.pytorch.org/whl/cpu || goto :error
pip install -r requirements.txt || goto :error
echo.
echo Setup complete. Run start.bat
pause
exit /b 0
:error
echo Setup failed. See the messages above.
pause
exit /b 1
