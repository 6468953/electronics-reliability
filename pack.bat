@echo off
chcp 936 >nul 2>&1
cd /d "%~dp0"
title 打包发布版

echo.
echo  ============================================================
echo    生成可迁移发布包
echo  ============================================================
echo.

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo  [x] 没找到 Python，无法打包。
        pause
        exit /b 1
    )
    set "PY=python"
)

REM 参数原样传给 pack.py：
REM     pack.bat                 普通包（目标机器需联网装依赖）
REM     pack.bat --with-wheels   连依赖一起带，完全离线
REM     pack.bat --with-db       连当前数据库一起带
"%PY%" tools\pack.py %*

echo.
pause
