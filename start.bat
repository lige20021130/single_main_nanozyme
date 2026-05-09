@echo off
chcp 65001 >nul 2>&1
title Nanozyme Extraction System
cd /d "%~dp0"

echo ================================================
echo    Nanozyme Extraction System
echo ================================================
echo.

set PYTHON_EXE=

if exist "D:\conda\python.exe" (
    set "PYTHON_EXE=D:\conda\python.exe"
    echo [OK] Found Python: D:\conda\python.exe
)

if exist "D:\conda\envs\TraeAI-5\python.exe" (
    set "PYTHON_EXE=D:\conda\envs\TraeAI-5\python.exe"
    echo [OK] Found Python: D:\conda\envs\TraeAI-5\python.exe
)

if exist "C:\Users\%USERNAME%\anaconda3\python.exe" (
    set "PYTHON_EXE=C:\Users\%USERNAME%\anaconda3\python.exe"
    echo [OK] Found Python: C:\Users\%USERNAME%\anaconda3\python.exe
)

if exist "C:\Users\%USERNAME%\miniconda3\python.exe" (
    set "PYTHON_EXE=C:\Users\%USERNAME%\miniconda3\python.exe"
    echo [OK] Found Python: C:\Users\%USERNAME%\miniconda3\python.exe
)

if exist "C:\ProgramData\anaconda3\python.exe" (
    set "PYTHON_EXE=C:\ProgramData\anaconda3\python.exe"
    echo [OK] Found Python: C:\ProgramData\anaconda3\python.exe
)

if "%PYTHON_EXE%"=="" (
    where python >nul 2>&1
    if %errorlevel%==0 (
        set "PYTHON_EXE=python"
        echo [OK] Found Python in PATH
    ) else (
        echo [ERROR] Python not found!
        echo.
        echo Please install Python 3.10+ and add to PATH
        echo Or modify this script to set PYTHON_EXE manually
        echo.
        pause
        exit /b 1
    )
)

echo.
echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" --version
echo.

"%PYTHON_EXE%" start.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Program exited with code: %errorlevel%
    echo.
    echo Troubleshooting:
    echo   1. Run: pip install -r requirements.txt
    echo   2. Check Python version (3.10+ required)
    echo   3. See: usage_guide.md for detailed help
    echo.
)
pause
