"""
app/security.py — 口令哈希与 JWT

【这个模块做什么】
1. 口令哈希：PBKDF2-HMAC-SHA256（标准库，无需额外依赖），存 "算法$迭代$盐$哈希" 格式；
2. 令牌签发/校验：JWT（HS256），载荷里放 user_id 与角色。

【为什么用 PBKDF2 而不是 bcrypt】
bcrypt 需要编译扩展，在 Windows 上装包经常失败；PBKDF2 是 hashlib 自带的，
安全强度对"内部工具/教学项目"完全够用（迭代 26 万次）。生产环境可平滑换成 argon2。

【注意】
密钥默认值是 dev 用的，部署时必须通过环境变量 JWT_SECRET 覆盖——
否则任何人都能自己签一个 admin 令牌。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt

from .config import settings

_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def create_access_token(user_id: int, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    except jwt.PyJWTError:
        return None
