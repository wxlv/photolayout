@echo off
REM PhotoLayout - Command Line Mode (double-click to run)
REM Keep this file pure ASCII to avoid codepage parsing issues.
cd /d "%~dp0"

call "%~dp0_bootstrap.bat" core
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" main.py

echo.
pause
