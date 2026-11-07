@echo off
:: Start OzMoEg Lifestyle Coach API server
:: Place a shortcut to this batch file in shell:startup if you want it auto-started

set SCRIPT_DIR=%~dp0
set API_SCRIPT=C:\Users\elsha\AppData\Local\hermes\skills\ozmoeg-lifestyle\scripts\api.py
set LOG_DIR=%SCRIPT_DIR%..\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: Kill any existing instance on port 8779 (find by window title if any)
taskkill /F /FI "WINDOWTITLE eq OzMoEg Lifestyle Coach*" 2>nul

cd /d C:\Users\elsha\AppData\Local\hermes\skills\ozmoeg-lifestyle\scripts
start "OzMoEg Lifestyle Coach API" python "%API_SCRIPT%"

echo OzMoEg Lifestyle Coach API starting on http://127.0.0.1:8779
timeout /t 2 > nul
curl -s http://127.0.0.1:8779/health
