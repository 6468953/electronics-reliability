"""
app/seed.py — 首次启动的种子数据

【这个模块做什么】
1. 建默认账号（admin / engineer）；
2. 建分类知识库（类目 + 关键词，从 JSON 种子导入）；
3. 建一个演示项目，并灌入一份模拟 BOM 且跑完自动分类。

【为什么要有演示项目】
第一次打开系统的用户面对空白页面无从下手。"演示项目"让他直接看到：
分类结果长什么样、待确认队列里有什么、未识别行是怎么被标出来的。
这是可用性设计，不是偷懒——但对生产部署应关闭（设置 DEMO_DATA=0）。
"""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import Category, Project, User
from .security import hash_password
from .services import classify as classify_service
from .services import kb as kb_service


def ensure_users(db: Session) -> None:
    if db.query(User).count() > 0:
        return
    db.add(
        User(
            username=settings.default_admin_user,
            password_hash=hash_password(settings.default_admin_password),
            display_name="系统管理员",
            role="admin",
        )
    )
    db.add(
        User(
            username=settings.default_engineer_user,
            password_hash=hash_password(settings.default_engineer_password),
            display_name="可靠性工程师",
            role="engineer",
        )
    )
    db.commit()


def ensure_kb(db: Session) -> None:
    kb_service.seed_from_json(db)


def ensure_demo_project(db: Session) -> None:
    if os.getenv("DEMO_DATA", "1") != "1":
        return
    if db.query(Project).count() > 0:
        return

    engineer = db.query(User).filter(User.role == "engineer").first()
    owner_id = engineer.id if engineer else db.query(User).first().id

    project = Project(
        name="演示项目 · 智能网关 GW-200",
        code="DEMO-001",
        owner_id=owner_id,
        description="系统预置的演示项目：200 行模拟 BOM，含边界 case 与预置问题零件，可直接跑完整流程。",
        target_years=5.0,
        target_survival=0.95,
        mtbf_threshold_hours=430000.0,
        status="bom_ready",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    from sim.generator import generate

    from .services import bom as bom_service

    rows = generate(scale=200, seed=42, include_cases=True, include_dirty=True)
    version = bom_service.create_version(
        db,
        project.id,
        "基准方案 v1",
        "simulated",
        "demo_200_42.csv",
        rows,
        [
            {"level": "warn", "code": "dup_pn", "message": "预置 1 条重复料号（演示校验提示）", "line_no": None},
            {"level": "warn", "code": "qty_empty", "message": "预置 1 条缺用量行，已按 1 处理", "line_no": None},
        ],
        owner_id,
    )
    project.current_bom_version_id = version.id
    project.status = "bom_ready"
    db.commit()

    classify_service.run_classification(db, version)
    project.status = "classified"
    db.commit()


def seed_all() -> None:
    db = SessionLocal()
    try:
        ensure_users(db)
        ensure_kb(db)
        ensure_demo_project(db)
    finally:
        db.close()
