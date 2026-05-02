@echo off
chcp 65001 >nul 2>&1
title 纳米酶文献提取系统

cd /d "%~dp0"

echo ============================================
echo   纳米酶文献提取系统 - Single Main Nanozyme
echo ============================================
echo.

python pdf_basic_gui.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [错误] 程序异常退出，错误代码: %ERRORLEVEL%
    pause
)
