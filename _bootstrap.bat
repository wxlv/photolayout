@echo off
REM PhotoLayout bootstrap (internal). Usage: _bootstrap.bat [core|web]
REM Keep this file pure ASCII to avoid codepage parsing issues.
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Please install Python 3.11+ and check "Add python.exe to PATH".
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist "%VENV_PY%" (
    echo First run: setting up the environment, please wait...
    python -m venv .venv
    if errorlevel 1 goto bootstrap_fail
    "%VENV_PY%" -m pip install --upgrade pip
    if errorlevel 1 goto bootstrap_fail
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 goto bootstrap_fail
    echo Environment ready.
)

if /i "%~1"=="web" (
    "%VENV_PY%" -m pip show gradio >nul 2>nul
    if errorlevel 1 (
        echo Installing gradio for the web UI...
        "%VENV_PY%" -m pip install gradio
        if errorlevel 1 goto bootstrap_fail
    )
)

exit /b 0

:bootstrap_fail
echo.
echo [ERROR] Setup failed. Please check your network connection and try again.
pause
exit /b 1
