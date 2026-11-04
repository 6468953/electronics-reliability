"""
tests/conftest.py — 测试环境准备

【为什么在这里设环境变量】
app.config 在导入时就读取 DATABASE_URL。如果在测试函数里再设，已经晚了——
连接串早就固定下来了。所以必须在任何 app 模块被导入之前设置，
conftest.py 是 pytest 唯一的"最早执行点"。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_DB = Path(tempfile.gettempdir()) / "reliability_test.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_TEST_DB}"
os.environ.setdefault("DEMO_DATA", "1")
os.environ.setdefault("JWT_SECRET", "test-secret")
