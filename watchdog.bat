@echo off
:: OzMoEg Trip Planner auto-restart watchdog
:: Runs invisibly via pythonw; checks API + tunnel health every 60s and restarts them if disconnected.
setlocal EnableDelayedExpansion

cd /d "C:\Users\openclaw\AppData\Local\hermes\skills\ozmoeg\trip_planner\scripts"
set API_DIR=C:\Users\openclaw\AppData\Local\hermes\skills\ozmoeg\trip_planner\scripts
set CLOUDFLARED="C:\Program Files (x86)\cloudflared\cloudflared.exe"
set TUNNEL_ID=73e22dd4-381e-4542-8d5a-e41d1682232d
set LOG=%API_DIR%\watchdog.log
set PYTHON=C:\Users\openclaw\AppData\Local\Python\pythoncore-3.14-64\python.exe

:: Log helper
echo [%date% %time%] Watchdog started >> %LOG%

:loop
set NEED_API=0
set NEED_TUNNEL=0

:: Check API health (local only; Cloudflare 530 can be a tunnel issue not API issue)
%PYTHON% -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8777/health', timeout=5)" >nul 2>&1
if errorlevel 1 set NEED_API=1

:: Check tunnel via cloudflared info command
%CLOUDFLARED% tunnel info %TUNNEL_ID% 2>&1 | findstr /C:"active connection" >nul
if errorlevel 1 (
    :: cloudflared info text changed; fall back to curl public health
    curl -s --max-time 8 https://trip-planner.aeyeing.com/health | findstr /C:"\"ok\": true" >nul
    if errorlevel 1 set NEED_TUNNEL=1
)

if %NEED_API%==1 (
    echo [%date% %time%] API down, restarting >> %LOG%
    taskkill /F /IM python.exe /FI "WINDOWTITLE eq tripplanner_api" >nul 2>&1
    taskkill /F /FI "IMAGENAME eq python.exe" /FI "COMMANDLINE eq *api.py*" >nul 2>&1
    start /B "" %PYTHON% "%API_DIR%\api.py" >nul 2>&1
)

if %NEED_TUNNEL%==1 (
    echo [%date% %time%] Tunnel down, restarting >> %LOG%
    taskkill /F /IM cloudflared.exe >nul 2>&1
    start /B "" %CLOUDFLARED% tunnel run %TUNNEL_ID% >nul 2>&1
)

if %NEED_API%==1 timeout /T 12 /NOBREAK >nul
if %NEED_TUNNEL%==1 timeout /T 20 /NOBREAK >nul

timeout /T 60 /NOBREAK >nul
goto loop
