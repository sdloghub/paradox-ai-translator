@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Paradox AI Translator

cd /d "%~dp0"

echo ===================================================
echo       Paradox AI Translator - Windows Launcher
echo ===================================================
echo.

if exist "WorkshopTranslator.exe" (
    echo [Launcher] Starting WorkshopTranslator.exe ...
    start "" "WorkshopTranslator.exe" %*
    exit /b 0
)

if exist "dist\WorkshopTranslator\WorkshopTranslator.exe" (
    echo [Launcher] Starting dist\WorkshopTranslator\WorkshopTranslator.exe ...
    start "" "dist\WorkshopTranslator\WorkshopTranslator.exe" %*
    exit /b 0
)

echo [Launcher] Source mode detected. Checking Python environment...

set "PYTHON_EXE="

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    where py >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=py -3"
    ) else (
        where python >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_EXE=python"
        )
    )
)

if "%PYTHON_EXE%"=="" (
    echo [Error] Python environment not found!
    echo Please install Python 3.12+ from https://www.python.org/
    echo Make sure to check "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [Notice] Creating virtual environment in .venv ...
    %PYTHON_EXE% -m venv .venv
    if exist ".venv\Scripts\python.exe" (
        set "PYTHON_EXE=.venv\Scripts\python.exe"
        echo [Notice] Installing dependencies from requirements.txt ...
        .venv\Scripts\python.exe -m pip install -r requirements.txt
    )
) else (
    .venv\Scripts\python.exe -c "import openai" >nul 2>&1
    if !errorlevel! neq 0 (
        echo [Notice] Checking and updating dependencies ...
        .venv\Scripts\python.exe -m pip install -r requirements.txt
    )
)

echo.
echo [Launcher] Starting Paradox AI Translator workbench...
echo Open your browser at http://localhost:8765
echo Press Ctrl+C or close this window to stop.
echo.

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe workshop_app.py %*
) else (
    %PYTHON_EXE% workshop_app.py %*
)

if !errorlevel! neq 0 (
    echo.
    echo [Notice] Process exited with code !errorlevel!.
    pause
)
