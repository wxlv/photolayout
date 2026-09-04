@echo off
REM PhotoLayout - Web UI Mode (double-click to run; browser opens automatically)
REM Keep this file pure ASCII to avoid codepage parsing issues.
cd /d "%~dp0"

call "%~dp0_bootstrap.bat" web
if errorlevel 1 exit /b 1

echo Starting the web UI. Your browser will open automatically.
echo Close this window to stop the service.
".venv\Scripts\python.exe" main.py --web

echo.
pause
