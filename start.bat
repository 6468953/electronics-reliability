@echo off
chcp 936 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"

title 电子零件可靠性评估系统

echo.
echo  ============================================================
echo    电子零件可靠性评估系统  ·  一键启动
echo  ============================================================
echo.

REM NOTE: this file is saved in GBK (cp936) on purpose -- do not re-save as UTF-8.
REM The shell reads a .bat byte-wise; with a UTF-8 file it can slice a Chinese
REM character in half and then run the leftover fragment as a command (the
REM classic "'xx' is not recognized" error). GBK is double-byte, so that
REM failure mode cannot happen on Chinese Windows.

REM ---- Step 0: check the built frontend -------------------------------
REM Runtime only needs frontend\dist. Node.js is NOT required.
if not exist "frontend\dist\index.html" goto no_dist

REM ---- Step 1: locate python interpreter ------------------------------
REM Prefer the existing project venv, so nothing gets reinstalled.
set "PY=backend\.venv\Scripts\python.exe"
if exist "%PY%" goto have_venv
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto have_venv

set "SYS_PY="
where python >nul 2>&1
if not errorlevel 1 set "SYS_PY=python"
if not defined SYS_PY (
    where py >nul 2>&1
    if not errorlevel 1 set "SYS_PY=py -3"
)
if not defined SYS_PY goto no_python

echo  [1/4] 首次运行，正在创建运行环境（1-2 分钟，只做这一次）...
%SYS_PY% -m venv backend\.venv
if errorlevel 1 goto venv_failed
set "PY=backend\.venv\Scripts\python.exe"
if not exist "%PY%" goto venv_failed
goto check_deps

:have_venv
echo  [1/4] 使用项目自带运行环境

:check_deps
REM ---- Step 2: dependency self-check -----------------------------------
REM Import a few key packages instead of checking all; fast and reliable.
"%PY%" -c "import fastapi,uvicorn,jwt,jieba,reportlab,openpyxl,pydantic,sqlalchemy" >nul 2>&1
if not errorlevel 1 goto deps_ok

echo  [2/4] 正在安装依赖...
if exist "wheels" goto install_offline
echo        需要联网下载（首次约 50MB）。要离线部署请先运行 pack.bat
"%PY%" -m pip install -r backend\requirements.txt
if errorlevel 1 goto deps_failed
echo        依赖安装完成
goto pick_port

:install_offline
echo        使用离线包目录 wheels\
"%PY%" -m pip install --no-index --find-links wheels -r backend\requirements.txt
if errorlevel 1 goto deps_failed
echo        依赖安装完成
goto pick_port

:deps_ok
echo  [2/4] 依赖已就绪

:pick_port
REM ---- Step 3: find a free port ----------------------------------------
REM If 8000 is taken, shift up to 8010. Otherwise the window would die
REM instantly and the user has no clue why.
set PORT=8000
:probe_port
netstat -ano | findstr "LISTENING" | findstr ":!PORT! " >nul 2>&1
if errorlevel 1 goto port_found
if !PORT! geq 8010 goto no_port
set /a PORT=!PORT!+1
goto probe_port

:port_found
if not "!PORT!"=="8000" echo  [!] 8000 端口被占用，自动改用 !PORT!
set "URL=http://127.0.0.1:!PORT!"

echo  [3/4] 端口就绪：!PORT!
echo  [4/4] 启动服务...
echo.
echo  ------------------------------------------------------------
echo    界面地址：  !URL!
echo    接口文档：  !URL!/docs
echo    演示账号：  admin / admin123
echo                engineer / engineer123
echo.
echo    这个窗口就是服务本体 —— 关掉它（或按 Ctrl+C）服务就停。
echo    图形界面在浏览器里打开，不是桌面软件。
echo  ------------------------------------------------------------
echo.

REM Open the browser only after the port really accepts a connection.
REM A fixed 4s delay breaks on first run: installing 30+ packages can take a
REM minute, and the user ends up staring at 'cannot reach this site'.
start "" /b "%PY%" tools\wait_and_open.py !PORT! "!URL!"

REM --app-dir backend tells uvicorn where to find the app package, so we
REM never need to cd into a subdirectory (and data\ lands in the right place).
"%PY%" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port !PORT!

echo.
echo  服务已停止。如需再次使用，双击 start.bat 即可。
pause
exit /b 0

REM ======================= error branches ==============================
:no_dist
echo  [x] 找不到前端页面：frontend\dist\index.html
echo.
echo      你拿到的是"源码包"，需要先构建一次页面（之后就一直有了）：
echo          cd frontend
echo          npm install
echo          npm run build
echo.
echo      如果拿到的是"发布包"，说明打包漏了 dist，请找提供方重新打包。
echo.
pause
exit /b 1

:no_python
echo  [x] 没找到 Python。
echo.
echo      请先安装 Python 3.10+：https://www.python.org/downloads/
echo      安装时务必勾选 "Add Python to PATH"，装完重开这个窗口再双击。
echo.
pause
exit /b 1

:venv_failed
echo  [x] 创建虚拟环境失败。请确认 Python 版本 ^>= 3.10：python --version
echo.
pause
exit /b 1

:deps_failed
echo.
echo  [x] 依赖安装失败。常见原因与解法：
echo      1^) 网络慢或超时，换国内镜像再试：
echo         "%PY%" -m pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo      2^) 公司网络要走代理，先设好 HTTP_PROXY / HTTPS_PROXY 环境变量
echo.
pause
exit /b 1

:no_port
echo  [x] 8000-8010 端口都被占用了，请先关掉占用的程序再试。
echo.
pause
exit /b 1
