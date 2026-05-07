@echo off
title Nanozyme Extraction System

cd /d "%~dp0"

set CUDA_VISIBLE_DEVICES=0
set PYTHONWARNINGS=ignore:.*pin_memory.*:UserWarning

echo ============================================
echo   Nanozyme Extraction System
echo ============================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.9+ and add to PATH.
    echo.
    echo If using Conda, run in Anaconda Prompt:
    echo   conda activate TraeAI-3
    echo   cd /d "%~dp0"
    echo   python nanozyme_gui.py
    echo.
    pause
    exit /b 1
)

python --version 2>nul
echo.
echo Starting GUI...
echo.

python nanozyme_gui.py 2>&1

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Program exited with code: %ERRORLEVEL%
    echo.
    echo Troubleshooting:
    echo 1. Make sure Python 3.9+ is installed and Conda env is activated
    echo 2. Install dependencies: pip install -r requirements.txt
    echo 3. Make sure config.yaml exists
    echo.
    echo If using Conda, run in Anaconda Prompt:
    echo   conda activate TraeAI-3
    echo   cd /d "%~dp0"
    echo   python nanozyme_gui.py
    echo.
    pause
)
