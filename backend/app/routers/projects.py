"""
app/routers/projects.py — 项目维度管理

【这个模块做什么】
项目的增删改查 + 全流程状态时间线。
一个项目对应：一份当前 BOM、一次分类结果、多轮评估、多份报告——这正是需求里
"项目维度管理、全流程状态可追踪"的含义。

【状态机】
    draft → bom_ready → classified → assessed → reported → archived
状态不靠人手动改，而是由各自的动作推进（上传 BOM 自动 bom_ready，跑完分类自动 classified…）。
这里提供 timeline 端点，把每个节点的时间与产物列出来，方便回答"这个项目走到哪一步了"。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, log_action
from ..models import Assessment, BomVersion, Project, Report, User
from ..schemas import ProjectCreate, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["项目"])


def _gen_code(name: str, db: Session) -> str:
    """自动生成项目编号：P-YYYYMMDD-NN。用户没填 code 时用。"""
    base = "P-" + datetime.now().strftime("%Y%m%d")
    n = 1
    while db.query(Project).filter(Project.code == f"{base}-{n:02d}").first():
        n += 1
    return f"{base}-{n:02d}"


def _project_dict(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "code": p.code,
        "description": p.description,
        "status": p.status,
        "target_years": p.target_years,
        "target_survival": p.target_survival,
        "mtbf_threshold_hours": p.mtbf_threshold_hours,
        "current_bom_version_id": p.current_bom_version_id,
        "owner_id": p.owner_id,
        "created_at": p.created_at.isoformat(timespec="seconds"),
        "updated_at": p.updated_at.isoformat(timespec="seconds"),
    }


def get_project_or_404(db: Session, project_id: int, user: User) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="项目不存在")
    # 工程师只能看自己的项目；管理员可看全部。这是最基础的越权防护。
    if user.role != "admin" and p.owner_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该项目")
    return p


@router.get("")
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Project)
    if user.role != "admin":
        q = q.filter(Project.owner_id == user.id)
    rows = q.order_by(Project.updated_at.desc()).all()

    out = []
    for p in rows:
        d = _project_dict(p)
        latest = (
            db.query(Assessment)
            .filter(Assessment.project_id == p.id)
            .order_by(Assessment.created_at.desc())
            .first()
        )
        d["latest_assessment"] = (
            {
                "id": latest.id,
                "verdict": latest.verdict,
                "mtbf_hours": latest.mtbf_hours,
                "r_at_target": latest.r_at_target,
                "created_at": latest.created_at.isoformat(timespec="seconds"),
            }
            if latest
            else None
        )
        d["bom_version_count"] = db.query(BomVersion).filter(BomVersion.project_id == p.id).count()
        out.append(d)
    return out


@router.post("", status_code=201)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    code = (body.code or "").strip() or _gen_code(body.name, db)
    if db.query(Project).filter(Project.code == code).first():
        raise HTTPException(status_code=400, detail=f"项目编号 {code} 已存在")

    p = Project(
        name=body.name,
        code=code,
        owner_id=user.id,
        description=body.description,
        target_years=body.target_years,
        target_survival=body.target_survival,
        mtbf_threshold_hours=body.mtbf_threshold_hours,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    log_action(db, user, "create_project", "project", p.id, p.name)
    return _project_dict(p)


@router.get("/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = get_project_or_404(db, project_id, user)
    d = _project_dict(p)
    versions = (
        db.query(BomVersion)
        .filter(BomVersion.project_id == p.id)
        .order_by(BomVersion.version_no.desc())
        .all()
    )
    d["bom_versions"] = [
        {
            "id": v.id,
            "version_no": v.version_no,
            "label": v.label,
            "source": v.source,
            "filename": v.filename,
            "row_count": v.row_count,
            "qty_total": v.qty_total,
            "created_at": v.created_at.isoformat(timespec="seconds"),
        }
        for v in versions
    ]
    d["assessment_count"] = db.query(Assessment).filter(Assessment.project_id == p.id).count()
    return d


@router.patch("/{project_id}")
def update_project(
    project_id: int,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = get_project_or_404(db, project_id, user)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    log_action(db, user, "update_project", "project", p.id, str(data))
    return _project_dict(p)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = get_project_or_404(db, project_id, user)
    db.delete(p)
    db.commit()
    log_action(db, user, "delete_project", "project", project_id, p.name)
    return None


@router.get("/{project_id}/timeline")
def timeline(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """全流程追踪：每个节点发生了什么、产物 id 是多少。"""
    p = get_project_or_404(db, project_id, user)
    events = [{"step": "创建项目", "at": p.created_at.isoformat(timespec="seconds"), "detail": p.name, "done": True}]

    versions = db.query(BomVersion).filter(BomVersion.project_id == p.id).order_by(BomVersion.version_no).all()
    for v in versions:
        events.append(
            {
                "step": f"导入 BOM（v{v.version_no}）",
                "at": v.created_at.isoformat(timespec="seconds"),
                "detail": f"{v.label} · {v.row_count} 行 · 来源 {v.source}",
                "done": True,
                "bom_version_id": v.id,
            }
        )

    if versions:
        v = versions[-1]
        classified = sum(1 for i in v.items if i.category_id)
        events.append(
            {
                "step": "零件分类",
                "at": v.created_at.isoformat(timespec="seconds"),
                "detail": f"已归类 {classified}/{v.row_count} 行",
                "done": classified == v.row_count and v.row_count > 0,
            }
        )

    assessments = db.query(Assessment).filter(Assessment.project_id == p.id).order_by(Assessment.created_at).all()
    if not assessments:
        events.append({"step": "可靠性评估", "at": "", "detail": "尚未评估", "done": False})
    for a in assessments:
        events.append(
            {
                "step": f"评估（{a.standard} / {a.mode}）",
                "at": a.created_at.isoformat(timespec="seconds"),
                "detail": f"MTBF {a.mtbf_hours:,.0f} h · R(t) {a.r_at_target*100:.2f}% · {a.verdict}",
                "done": True,
                "assessment_id": a.id,
            }
        )

    reports = db.query(Report).filter(Report.project_id == p.id).order_by(Report.created_at).all()
    for r in reports:
        events.append(
            {
                "step": f"生成报告（{r.kind.upper()}）",
                "at": r.created_at.isoformat(timespec="seconds"),
                "detail": f"{r.file_size/1024:.0f} KB · 判定 {r.verdict}",
                "done": True,
                "report_id": r.id,
            }
        )
    return {"project": _project_dict(p), "events": events}
