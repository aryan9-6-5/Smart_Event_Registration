@echo off
setlocal
title Smart Event Registration System

echo ========================================================
echo       Smart Event Registration System - Launcher
echo ========================================================
echo.

:: Detect Python executable
set "PYTHON_CMD=python"
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=venv\Scripts\python.exe"
)

%PYTHON_CMD% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found on your system PATH!
    echo Please install Python 3.10+ and add it to your PATH.
    pause
    exit /b 1
)

echo [INFO] Detected Python:
%PYTHON_CMD% --version
echo.
echo Select an option:
echo   [1] Start Production Server (Waitress / wsgi.py)
echo   [2] Start Development Server (Flask / app.py)
echo   [3] Run Automated Test Suite (pytest)
echo   [4] Open Registration Portal in Browser
echo   [5] Open Admin Portal in Browser
echo   [6] Exit
echo.

choice /c 123456 /t 10 /d 1 /m "Press [1-6] (auto-starts #1 in 10s): "
set "SELECTED=%errorlevel%"

if "%SELECTED%"=="1" (
    echo.
    echo [INFO] Starting Production Server on http://127.0.0.1:5000 ...
    echo [INFO] Press Ctrl+C in this window to stop the server.
    echo.
    %PYTHON_CMD% wsgi.py
)
if "%SELECTED%"=="2" (
    echo.
    echo [INFO] Starting Development Server on http://127.0.0.1:5000 ...
    echo [INFO] Press Ctrl+C in this window to stop the server.
    echo.
    %PYTHON_CMD% app.py
)
if "%SELECTED%"=="3" (
    echo.
    echo [INFO] Running test suite...
    echo.
    %PYTHON_CMD% -m pytest tests/ -v
    echo.
    pause
)
if "%SELECTED%"=="4" (
    echo [INFO] Opening Registration Portal...
    start http://127.0.0.1:5000/
)
if "%SELECTED%"=="5" (
    echo [INFO] Opening Admin Portal...
    start http://127.0.0.1:5000/admin
)
if "%SELECTED%"=="6" (
    echo Exiting.
)
