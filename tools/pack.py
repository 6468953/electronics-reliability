"""
tools/pack.py — 打一个可迁移的发布包

【做什么】
把「运行系统真正需要的东西」收拢到一个干净目录，并压成 zip。拿到的人解压、
双击 start.bat 就能用，不需要 Node.js，也不需要联网装依赖（如果带了 wheels）。

【为什么不是简单的"整个文件夹压缩"】
    backend/.venv（370MB）和 frontend/node_modules（263MB）里塞满了只有当前机器、
    当前 Python 版本才认得的绝对路径。原样拷走，十有八九在新机器上跑不起来，
    还要多背 630MB。真正必需的是源码 + 已经构建好的 frontend/dist（约 2.5MB）。

【用法】
    python tools/pack.py                    # 普通发布包（目标机器需联网装依赖）
    python tools/pack.py --with-wheels      # 连依赖 wheel 一起打包，完全离线可用
    python tools/pack.py --with-db          # 连当前演示数据库一起带走（保留已录入的项目）
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG_NAME = "可靠性评估系统-v1.0"
OUT_ROOT = ROOT / "发布包"
STAGE = OUT_ROOT / PKG_NAME
ZIP_PATH = OUT_ROOT / f"{PKG_NAME}.zip"

# 需要整目录带走的
INCLUDE_DIRS = [
    "docs",
    "backend/app",
    "backend/core",
    "backend/params",
    "backend/sim",
    "backend/tests",
    "frontend/dist",
]
# 需要单独文件的
#
# 【为什么发布包里不放 frontend/src 和 frontend/index.html】
#   frontend/index.html 是 Vite 的“源模板”，里面写的是 <script src="/src/main.tsx">。
#   它长得就像“双击这个打开系统”，但双击后既加载不到脚本、也连不上后端，
#   只会得到白屏或一句 Failed to fetch —— 是纯粹的诱饵文件。
#   发布包的定位是「拿来就跑的运行版」，只需要已构建好的 dist；
#   要改前端请在源码仓库里改，改完 npm run build 再重新打包。
INCLUDE_FILES = [
    "README.md",
    "start.bat",
    "start.sh",
    "backend/requirements.txt",
    # start.bat 用它等端口就绪后再开浏览器；缺了它只是不自动开浏览器，服务仍能起来，
    # 但首次启动体验会退化，所以必须带上。
    "tools/wait_and_open.py",
]
# 这些目录里的内容一律不要（体积大 / 与机器绑定 / 是缓存）
EXCLUDE_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".vite", "node_modules", ".venv"}


def _ignore(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n in EXCLUDE_NAMES or n.endswith(".pyc")}


def _need_dist() -> None:
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        print("[x] 缺少前端构建产物。请先执行：cd frontend && npm install && npm run build")
        sys.exit(1)


def _download_wheels() -> None:
    """把后端依赖预下载到 wheels/，让目标机器能完全离线安装。

    【为什么不能只跑一次 pip download】
        pip download 遇到只发布源码包（sdist）的库（本项目里的 jieba 就是），
        会把 xxx.tar.gz 原样存下来，安装时再现场编译。而 Python 3.12 起
        `python -m venv` 不再自带 setuptools，目标机器一编译就报
        "Could not find a version that satisfies the requirement setuptools>=40.8.0"，
        离线环境直接卡死。

        所以这里多做两步：
          1) 把 wheels/ 里残留的 .tar.gz 用 pip wheel 预先编译成 .whl
             （编译发生在打包机上，这台机器有网、有构建链）；
          2) 顺手把 setuptools / wheel 也下进来兜底，万一还有别的包需要构建。
    """
    wheels = ROOT / "wheels"
    wheels.mkdir(exist_ok=True)
    py = sys.executable
    print("[3/5] 预下载依赖（需要联网，约 50MB）...")

    r = subprocess.run(
        [py, "-m", "pip", "download", "-r", "backend/requirements.txt", "-d", "wheels"],
        cwd=ROOT,
    )
    if r.returncode != 0:
        print("[!] 依赖下载失败，发布包将需要目标机器联网安装。")
        return

    # 兜底构建链：sdist 现场构建时会用到
    subprocess.run(
        [py, "-m", "pip", "download", "setuptools", "wheel", "-d", "wheels"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
    )

    # 把 sdist 预编译成 whl，避免目标机器在无网环境里现场编译
    sdists = sorted(wheels.glob("*.tar.gz"))
    for sdist in sdists:
        print(f"      预编译源码包：{sdist.name}")
        rr = subprocess.run(
            [py, "-m", "pip", "wheel", str(sdist), "-w", str(wheels), "--no-deps"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        if rr.returncode == 0:
            sdist.unlink()  # 有了 whl 就不必再带 tar.gz
        else:
            print(f"      [!] {sdist.name} 预编译失败，保留源码包（目标机器需可编译）")

    n_whl = len(list(wheels.glob("*.whl")))
    n_sdist = len(list(wheels.glob("*.tar.gz")))
    print(f"      已准备 {n_whl} 个 wheel" + (f"，{n_sdist} 个源码包" if n_sdist else ""))
    if n_sdist:
        print("      [!] 仍有源码包，离线安装可能失败，请检查构建链")


def main() -> None:
    ap = argparse.ArgumentParser(description="生成可迁移发布包")
    ap.add_argument("--with-wheels", action="store_true", help="连依赖 wheel 一起打包（离线可用）")
    ap.add_argument("--with-db", action="store_true", help="连当前 SQLite 数据库一起打包")
    args = ap.parse_args()

    print("[1/5] 检查前端构建产物...")
    _need_dist()

    print(f"[2/5] 清理旧目录：{OUT_ROOT}")
    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    OUT_ROOT.mkdir(parents=True)

    if args.with_wheels:
        _download_wheels()
    else:
        print("[3/5] 跳过 wheel 预下载（目标机器需联网装依赖；加 --with-wheels 可离线）")

    print("[4/5] 收集文件...")
    (STAGE / "backend" / "data" / "reports").mkdir(parents=True, exist_ok=True)
    (STAGE / "backend" / "data" / "uploads").mkdir(parents=True, exist_ok=True)
    (STAGE / "backend" / "data" / "reports" / ".gitkeep").touch()
    (STAGE / "backend" / "data" / "uploads" / ".gitkeep").touch()

    total = 0
    for rel in INCLUDE_DIRS:
        src = ROOT / rel
        if not src.exists():
            print(f"      [skip] {rel} 不存在")
            continue
        dst = STAGE / rel
        shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True)

    for rel in INCLUDE_FILES:
        src = ROOT / rel
        if not src.exists():
            continue
        dst = STAGE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    if args.with_db:
        db = ROOT / "backend" / "data" / "reliability.db"
        if db.exists():
            shutil.copy2(db, STAGE / "backend" / "data" / "reliability.db")
            print("      已带上演示数据库")
        else:
            print("      [skip] 没有找到数据库，跳过")

    if (ROOT / "wheels").exists() and args.with_wheels:
        shutil.copytree(ROOT / "wheels", STAGE / "wheels", dirs_exist_ok=True)

    for f in STAGE.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    print(f"      共 {sum(1 for f in STAGE.rglob('*') if f.is_file())} 个文件，{total / 1024 / 1024:.1f} MB")

    print("[5/5] 压缩...")
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in STAGE.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(OUT_ROOT))
    print(f"      完成：{ZIP_PATH}  ({ZIP_PATH.stat().st_size / 1024 / 1024:.1f} MB)")

    print()
    print("=" * 62)
    print(f" 发布包目录：{STAGE}")
    print(f" 压缩包：    {ZIP_PATH}")
    print()
    print(" 拿到包的人怎么用：")
    print("   1) 解压到任意位置（路径里最好别有中文和空格）")
    print("   2) Windows 双击 start.bat；macOS/Linux 执行 ./start.sh")
    print("   3) 浏览器自动打开 http://127.0.0.1:8000 ，账号 admin / admin123")
    print()
    print(" 目标机器只需要 Python 3.10+，不需要 Node.js。")
    if not args.with_wheels:
        print(" 注意：本包未带 wheels，目标机器首次启动需要联网装依赖。")
    print("=" * 62)


if __name__ == "__main__":
    main()
