@echo off
chcp 65001 >nul 2>&1
title 纳米酶文献提取系统

cd /d "%~dp0"

set CUDA_VISIBLE_DEVICES=0
set PYTHONWARNINGS=ignore:.*pin_memory.*:UserWarning

echo ============================================
echo   纳米酶文献提取系统 - Single Main Nanozyme
echo ============================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] 未找到 Python，请确保 Python 已安装并添加到系统 PATH
    echo.
    echo 如果使用 Conda，请先在 Anaconda Prompt 中运行:
    echo   conda activate TraeAI-3
    echo   cd /d "%~dp0"
    echo   python nanozyme_gui.py
    echo.
    pause
    exit /b 1
)

python --version 2>nul
echo.
echo 正在启动 GUI 界面...
echo.

python nanozyme_gui.py 2>&1

if %ERRORLEVEL% neq 0 (
    echo.
    echo [错误] 程序异常退出，错误代码: %ERRORLEVEL%
    echo.
    echo 常见问题排查:
    echo 1. 请确保已安装 Python 3.9+ 并激活正确的 Conda 环境
    echo 2. 请确保已安装所有依赖: pip install -r requirements.txt
    echo 3. 请确保 config.yaml 配置文件存在且正确
    echo.
    echo 如果使用 Conda，请在 Anaconda Prompt 中运行:
    echo   conda activate TraeAI-3
    echo   cd /d "%~dp0"
    echo   python nanozyme_gui.py
    echo.
    pause
)