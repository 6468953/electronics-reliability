"""
app/routers/auth.py — 登录与用户管理

【这个模块做什么】
登录签发 JWT、查询当前用户；管理员可建用户、启停用户。
不提供公开注册（内部工具的常见做法）：账号由管理员开设，避免演示环境被人乱注。
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, log_action, require_admin
from ..models import User
from ..schemas import LoginRequest, TokenOut, UserCreate
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        # 刻意不区分"用户不存在"和"密码错误"，避免账号枚举
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该账号已停用")

    token = create_access_token(user.id, user.username, user.role)
    log_action(db, user, "login", "user", user.id)
    return TokenOut(
        access_token=token,
        user={
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name or user.username,
            "role": user.role,
        },
    )


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "is_active": user.is_active,
    }


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> List[dict]:
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat(timespec="seconds"),
        }
        for u in db.query(User).order_by(User.id).all()
    ]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    u = User(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.username,
        role=body.role,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    log_action(db, admin, "create_user", "user", u.id, f"role={u.role}")
    return {"id": u.id, "username": u.username, "role": u.role}


@router.patch("/users/{user_id}/active")
def toggle_user(
    user_id: int,
    is_active: bool,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.id == admin.id and not is_active:
        raise HTTPException(status_code=400, detail="不能停用自己的账号")
    u.is_active = is_active
    db.commit()
    log_action(db, admin, "toggle_user", "user", u.id, f"is_active={is_active}")
    return {"id": u.id, "is_active": u.is_active}
