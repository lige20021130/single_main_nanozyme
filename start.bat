@echo off
title Nanozyme Extraction System

cd /d "%~dp0"

set CUDA_VISIBLE_DEVICES=0
set PYTHONWARNINGS=ignore:.*pin_memory.*:UserWarning

set PYTHON_EXE=

if exist "D:\conda\python.exe" (
    set "PYTHON_EXE=D:\conda\python.exe"
)

if exist "C:\Users\%USERNAME%\anaconda3\python.exe" (
    set "PYTHON_EXE=C:\Users\%USERNAME%\anaconda3\python.exe"
)

if exist "C:\Users\%USERNAME%\miniconda3\python.exe" (
    set "PYTHON_EXE=C:\Users\%USERNAME%\miniconda3\python.exe"
)

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PYTHON_EXE=python"
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] Python not found.
    echo.
    echo Please run in Anaconda Prompt:
    echo   conda activate base
    echo   cd /d "%~dp0"
    echo   python nanozyme_gui.py
    echo.
    pause
    exit /b 1
)

echo ============================================
echo   Nanozyme Extraction System
echo ============================================
echo.
echo Using: %PYTHON_EXE%
"%PYTHON_EXE%" --version 2>nul
echo.
echo Starting GUI...
echo.

"%PYTHON_EXE%" nanozyme_gui.py 2>&1

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Program exited with code: %ERRORLEVEL%
    echo.
    echo Troubleshooting:
    echo 1. Make sure Python 3.9+ is installed
    echo 2. Install dependencies: pip install -r requirements.txt
    echo 3. Make sure config.yaml exists
    echo.
    echo Or run in Anaconda Prompt:
    echo   conda activate base
    echo   cd /d "%~dp0"
    echo   python nanozyme_gui.py
    echo.
    pause
)
