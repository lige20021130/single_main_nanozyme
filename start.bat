@echo off
title Nanozyme Extraction System
cd /d "%~dp0"

set PYTHON_EXE=
if exist "D:\conda\python.exe" set "PYTHON_EXE=D:\conda\python.exe"
if exist "C:\Users\%USERNAME%\anaconda3\python.exe" set "PYTHON_EXE=C:\Users\%USERNAME%\anaconda3\python.exe"
if exist "C:\Users\%USERNAME%\miniconda3\python.exe" set "PYTHON_EXE=C:\Users\%USERNAME%\miniconda3\python.exe"
if "%PYTHON_EXE%"=="" set "PYTHON_EXE=python"

"%PYTHON_EXE%" start.py
pause
