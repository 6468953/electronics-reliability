"""
app/deps.py — FastAPI 依赖：鉴权、角色控制、操作日志

【这个模块做什么】
- `get_current_user`：从 Authorization: Bearer <token> 解析当前用户；
- `require_admin`：管理员专用端点用（参数库、用户管理）；
- `log_action`：写操作日志。日志不是可选项——评估报告的每个数字都可能被追责，
  必须能回答"谁在什么时候用哪份参数算的"。
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import OperationLog, User
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期")
    payload = decode_token(creds.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已停用")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def log_action(
    db: Session,
    user: Optional[User],
    action: str,
    target_type: str = "",
    target_id: Optional[int] = None,
    detail: str = "",
    request: Optional[Request] = None,
) -> None:
    """写一条操作日志。失败不影响主流程（日志不能把业务搞挂）。"""
    try:
        db.add(
            OperationLog(
                user_id=user.id if user else None,
                username=user.username if user else "",
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=detail[:2000],
            )
        )
        db.commit()
    except Exception:  # pragma: no cover
        db.rollback()
