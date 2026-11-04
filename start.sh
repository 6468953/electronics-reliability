#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# start.sh — macOS / Linux 一键启动
#
# 用法：
#     chmod +x start.sh && ./start.sh        （首次需要给执行权限）
#     或： bash start.sh
#
# 和 start.bat 做的是同一件事：检查页面 → 准备 Python 环境 → 装依赖 →
# 挑空闲端口 → 启动服务 → 自动开浏览器。运行期不需要 Node.js。
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

echo
echo " ============================================================"
echo "   电子零件可靠性评估系统  ·  一键启动"
echo " ============================================================"
echo

# --- 0. 前端页面检查 ------------------------------------------------------
if [ ! -f "frontend/dist/index.html" ]; then
    cat <<'EOF'
 [x] 找不到前端页面：frontend/dist/index.html

     你拿到的是"源码包"，需要先构建一次页面（之后就一直有了）：
         cd frontend
         npm install
         npm run build

     如果拿到的是"发布包"，说明打包漏了 dist，请找提供方重新打包。
EOF
    exit 1
fi

# --- 1. 准备 Python ------------------------------------------------------
PY=""
if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
    echo " [1/4] 使用项目自带运行环境 .venv"
else
    SYS_PY=""
    for cand in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$cand" >/dev/null 2>&1; then
            SYS_PY="$cand"
            break
        fi
    done
    if [ -z "$SYS_PY" ]; then
        echo " [x] 没找到 Python。请先安装 Python 3.10+（macOS 可用 brew install python@3.12）。"
        exit 1
    fi
    echo " [1/4] 首次运行，正在创建运行环境（1-2 分钟，只做这一次）..."
    "$SYS_PY" -m venv .venv
    PY=".venv/bin/python"
fi

# --- 2. 依赖自检（只 import 关键包，快且不误判） --------------------------
if "$PY" -c "import fastapi,uvicorn,jwt,jieba,reportlab,openpyxl,pydantic,sqlalchemy" >/dev/null 2>&1; then
    echo " [2/4] 依赖已就绪"
else
    echo " [2/4] 正在安装依赖..."
    if [ -d "wheels" ]; then
        echo "       使用离线包目录 wheels/"
        "$PY" -m pip install --no-index --find-links wheels -r backend/requirements.txt
    else
        echo "       需要联网下载（首次约 50MB）"
        "$PY" -m pip install -r backend/requirements.txt
    fi
    echo "       依赖安装完成"
fi

# --- 3. 挑空闲端口 -------------------------------------------------------
PORT=8000
while [ "$PORT" -le 8010 ]; do
    if ! (command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1) &&
       ! (command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$PORT "); then
        break
    fi
    PORT=$((PORT + 1))
done
if [ "$PORT" -gt 8010 ]; then
    echo " [x] 8000-8010 端口都被占用了，请先关掉占用的程序再试。"
    exit 1
fi
[ "$PORT" != "8000" ] && echo " [!] 8000 端口被占用，自动改用 $PORT"

URL="http://127.0.0.1:$PORT"
echo " [3/4] 端口就绪：$PORT"
echo " [4/4] 启动服务..."
echo
echo " ------------------------------------------------------------"
echo "   界面地址：  $URL"
echo "   接口文档：  $URL/docs"
echo "   演示账号：  admin / admin123"
echo "               engineer / engineer123"
echo
echo "   这个终端就是服务本体 —— 关掉它（或按 Ctrl+C）服务就停。"
echo "   图形界面在浏览器里打开，不是桌面软件。"
echo " ------------------------------------------------------------"
echo

# 等端口真的能连上再开浏览器。
# 固定 sleep 4 在首次运行时不成立：要装 30 多个包，可能超过一分钟，
# 那时打开浏览器只会显示"无法访问此网站"，被误认为启动失败。
(
    "$PY" tools/wait_and_open.py "$PORT" "$URL" >/dev/null 2>&1
) &

exec "$PY" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$PORT"
