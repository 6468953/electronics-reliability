"""
tools/wait_and_open.py — 等后端真正能连上了，再打开浏览器

【为什么需要单独的脚本】
start.bat 原本是在启动 uvicorn 之后固定等 4 秒就调 start 打开浏览器。
这个"4 秒"只在"依赖已经装好、数据库已经有"的机器上成立。首次运行要装 30 多个包，
可能要 1~2 分钟；那 4 秒过去时端口还没开始监听，浏览器只会显示"无法访问此网站"，
使用者第一反应就是"这东西坏了"。

【怎么做】
轮询 TCP 连接，连上了再开浏览器。最多等 180 秒，超时就不开——
宁可让人看到控制台里的报错，也不要打开一个白屏页把真正的原因盖住。

用法（由 start.bat 在后台调用）：
    python tools/wait_and_open.py <port> [url]
"""

from __future__ import annotations

import socket
import sys
import time
import webbrowser

TIMEOUT_SECONDS = 180
POLL_INTERVAL = 0.3
CONNECT_TIMEOUT = 0.4


def wait_port(port: int) -> bool:
    """反复尝试连 127.0.0.1:port，连上就返回 True，超时返回 False。"""
    deadline = time.time() + TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), CONNECT_TIMEOUT):
                return True
        except OSError:
            # 端口还没监听（服务还在启动），或已被别的进程占着但拒绝连接。
            # 两种情况都继续等：真正的失败会由主窗口里的 uvicorn 报出来。
            time.sleep(POLL_INTERVAL)
    return False


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python tools/wait_and_open.py <port> [url]")
        return 2

    port = int(sys.argv[1])
    url = sys.argv[2] if len(sys.argv) > 2 else f"http://127.0.0.1:{port}"

    if not wait_port(port):
        print(f"[!] 等待 {TIMEOUT_SECONDS}s 后仍无法连接 {url}，未自动打开浏览器。")
        print("    请查看上方的错误信息；若服务确实没起来，重新双击 start.bat。")
        return 1

    webbrowser.open(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
