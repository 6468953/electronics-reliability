"""
app/config.py — 运行配置

【这个模块做什么】
集中存放路径、数据库地址、JWT 密钥与过期时间。全部可用环境变量覆盖，
这样本地开发（SQLite）和部署（PostgreSQL）不需要改代码。
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
PROJECT_DIR = BASE_DIR.parent                               # 仓库根
PARAM_DIR = BASE_DIR / "params"
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = DATA_DIR / "reports"
UPLOAD_DIR = DATA_DIR / "uploads"

for d in (DATA_DIR, REPORT_DIR, UPLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _read_version() -> str:
    """版本号的唯一来源是仓库根的 VERSION 文件。

    以前写死在 app/main.py 两处，改一次要记得改两遍 —— 实际上漏过，
    接口还在返回 1.0.0，文档已经写到 V1.2。现在只认这一个文件；
    读不到就返回 0.0.0，不让"版本号读不到"变成起不来的理由。
    """
    try:
        return (PROJECT_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


APP_VERSION = _read_version()


class Settings:
    app_name: str = "电子零件可靠性评估系统"
    app_version: str = APP_VERSION
    api_prefix: str = "/api/v1"

    # 默认 SQLite；迁移 PostgreSQL 只需 export DATABASE_URL=postgresql+psycopg://...
    database_url: str = os.getenv("DATABASE_URL", f"sqlite+pysqlite:///{DATA_DIR / 'reliability.db'}")

    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-secret-change-me-in-production")
    jwt_alg: str = "HS256"
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))

    param_dir: Path = Path(os.getenv("PARAM_DIR", str(PARAM_DIR)))
    report_dir: Path = REPORT_DIR
    upload_dir: Path = UPLOAD_DIR

    # 演示用默认账号（首次启动自动创建）
    default_admin_user: str = os.getenv("DEFAULT_ADMIN_USER", "admin")
    default_admin_password: str = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
    default_engineer_user: str = os.getenv("DEFAULT_ENGINEER_USER", "engineer")
    default_engineer_password: str = os.getenv("DEFAULT_ENGINEER_PASSWORD", "engineer123")

    # 前端构建产物目录。存在时后端会顺带把它托管在根路径（单端口部署，见 main.py）。
    dist_dir: Path = Path(os.getenv("DIST_DIR", str(PROJECT_DIR / "frontend" / "dist")))

    # 跨域白名单。默认只放行本地开发端口。
    # 单端口部署（前端由本后端托管）时是同源请求，压根不走 CORS，不需要改这里。
    # 前后端分开部署时用环境变量覆盖：
    #   CORS_ORIGINS="http://10.0.0.8:5173,https://rel.example.com"
    # 想全放开就设 CORS_ORIGINS="*"（仅建议在完全隔离的内网使用）。
    _cors_env = os.getenv("CORS_ORIGINS", "").strip()
    cors_origins = (
        [o.strip() for o in _cors_env.split(",") if o.strip()]
        if _cors_env
        else [
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:4173", "http://127.0.0.1:4173",
            "http://localhost:8000", "http://127.0.0.1:8000",
        ]
    )


settings = Settings()
