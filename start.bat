@echo off
chcp 65001 >nul 2>&1
title 纳米酶文献提取系统

cd /d "%~dp0"

set CUDA_VISIBLE_DEVICES=0
set PYTHONWARNINGS=ignore:.*pin_memory.*:UserWarning
set PATH=%PATH%;%SystemRoot%\system32

echo ============================================
echo   纳米酶文献提取系统 - Single Main Nanozyme
echo ============================================
echo.
echo 正在启动 GUI 界面...
echo.

python nanozyme_gui.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [错误] 程序异常退出，错误代码: %ERRORLEVEL%
    echo.
    echo 常见问题排查:
    echo 1. 请确保已安装 Python 3.9+
    echo 2. 请确保已安装所有依赖: pip install -r requirements.txt
    echo 3. 请确保 config.yaml 配置文件存在且正确
    pause
)