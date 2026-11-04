"""
app/db.py — 数据库连接与会话

【这个模块做什么】
建 SQLAlchemy 引擎、会话工厂，提供 FastAPI 依赖 `get_db()`。

【为什么用 SQLite 又不锁死在 SQLite】
开发期零配置（一个文件），但所有模型只用 ORM 通用类型（String/Integer/Float/Text/DateTime），
不用 SQLite 方言特性。迁移 PostgreSQL 时只改 DATABASE_URL + 跑迁移脚本。
"""

from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # pragma: no cover
        """打开外键约束。SQLite 默认不强制外键，不开这个删除父行会留下孤儿数据。"""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  确保模型已注册到 Base.metadata

    Base.metadata.create_all(bind=engine)
