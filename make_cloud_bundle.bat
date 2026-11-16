@echo off
REM Builds Desktop\AmharicDictate-cloud-upload.zip: training script + GPU runner + your voice recordings.
cd /d "%~dp0"
if exist cloud_upload rmdir /s /q cloud_upload
mkdir cloud_upload
copy /y tools\train_amharic_ctc.py cloud_upload\ >nul
copy /y cloud\run_on_gpu.sh cloud_upload\ >nul
copy /y cloud\README_CLOUD.md cloud_upload\ >nul
if exist "%APPDATA%\AmharicDictate\voice_data" xcopy /e /i /q /y "%APPDATA%\AmharicDictate\voice_data" cloud_upload\voice_data >nul
del /q "%USERPROFILE%\Desktop\AmharicDictate-cloud-upload.zip" 2>nul
tar -a -c -f "%USERPROFILE%\Desktop\AmharicDictate-cloud-upload.zip" -C cloud_upload .
echo.
echo Created: %USERPROFILE%\Desktop\AmharicDictate-cloud-upload.zip
pause
