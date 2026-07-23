@echo off
:: OzMoEg Trip Planner auto-restart watchdog
:: Waits 1 minute before launching so Ollama models can start first.
setlocal EnableDelayedExpansion

timeout /T 60 /NOBREAK >nul

set API_DIR=C:\Users\openclaw\AppData\Local\hermes\skills\ozmoeg\trip_planner\scripts
set PYTHON=C:\Users\openclaw\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe

start /B "" "%PYTHON%" "%API_DIR%\watchdog.py" >nul 2>&1
