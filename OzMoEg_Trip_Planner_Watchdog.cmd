@echo off
:: OzMoEg Trip Planner auto-restart watchdog
:: Runs invisibly via pythonw and relaunches api.py + cloudflared tunnel if either is down.
setlocal EnableDelayedExpansion
set API_DIR=C:\Users\openclaw\AppData\Local\hermes\skills\ozmoeg\trip_planner\scripts
set PYTHON=C:\Users\openclaw\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe

start /B "" "%PYTHON%" "%API_DIR%\watchdog.py" >nul 2>&1
