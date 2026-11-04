"""
app/routers/system.py — 参数库浏览、术语表、操作日志、总览

【这个模块做什么】
    GET /param-versions      参数库版本清单（标准名 + 来源 + 免责声明）
    GET /params/{standard}   某标准下的环境/质量档位与类别参数
    GET /glossary            术语表（前端术语页与全站 Hover 提示共用同一份数据）
    GET /logs                操作日志（管理员）
    GET /dashboard           首页统计

【为什么术语表由后端提供而不是前端写死】
"Hover 即解释"要求全站一致。如果前端各页面自己写一份文案，很快就会出现
MTBF 在 A 页说「平均无故障时间」、在 B 页说「平均寿命」的尴尬。放后端一处，改一次全站生效。
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.standards.loader import list_param_versions, load_param_set

from ..config import settings
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import Assessment, BomVersion, OperationLog, Project, Report, User
from ..services import assess as assess_service

router = APIRouter(tags=["系统"])


@router.get("/param-versions")
def param_versions(_: User = Depends(get_current_user)):
    return list_param_versions(str(settings.param_dir))


@router.get("/params/{standard}")
def param_detail(standard: str, _: User = Depends(get_current_user)):
    try:
        meta = assess_service.param_meta(standard)
        p = load_param_set(standard, str(settings.param_dir))
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"标准不存在或参数库损坏：{e}")

    meta["categories"] = [
        {
            "code": c.code,
            "name": c.name,
            "group": c.group,
            "family": c.family,
            "lambda_g": c.lambda_g,
            "stress_spec": c.stress_spec,
        }
        for c in p.category_list()
    ]
    return meta


@router.get("/glossary")
def glossary(
    group: Optional[str] = None,
    q: Optional[str] = None,
    _: User = Depends(get_current_user),
):
    path = settings.param_dir / "glossary_v1.json"
    if not path.exists():
        raise HTTPException(status_code=500, detail="术语表文件缺失")
    data = json.loads(path.read_text(encoding="utf-8"))

    terms = data.get("terms", [])
    if group:
        terms = [t for t in terms if t.get("group") == group]
    if q:
        needle = q.lower()
        terms = [
            t for t in terms
            if needle in (t.get("term", "") + t.get("abbr", "") + t.get("plain", "") + t.get("definition", "")).lower()
        ]
    data["terms"] = terms
    data["total"] = len(terms)
    return data


@router.get("/logs")
def list_logs(
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    rows = db.query(OperationLog).order_by(OperationLog.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "username": r.username,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "detail": r.detail,
            "created_at": r.created_at.isoformat(timespec="seconds"),
        }
        for r in rows
    ]


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pj = db.query(Project)
    if user.role != "admin":
        pj = pj.filter(Project.owner_id == user.id)
    projects = pj.all()
    ids = [p.id for p in projects] or [-1]

    assessments = db.query(Assessment).filter(Assessment.project_id.in_(ids)).all()
    pass_count = sum(1 for a in assessments if a.verdict == "PASS")
    fail_count = sum(1 for a in assessments if a.verdict == "FAIL")

    recent = (
        db.query(Assessment)
        .filter(Assessment.project_id.in_(ids))
        .order_by(Assessment.created_at.desc())
        .limit(5)
        .all()
    )
    return {
        "project_count": len(projects),
        "bom_version_count": db.query(BomVersion).filter(BomVersion.project_id.in_(ids)).count(),
        "assessment_count": len(assessments),
        "report_count": db.query(Report).filter(Report.project_id.in_(ids)).count(),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate": round(pass_count / len(assessments) * 100, 1) if assessments else 0.0,
        "recent_assessments": [assess_service.summary(a) for a in recent],
        "disclaimer": "本系统所有参数为示例数据，结果仅供演示与学习，不得作为产品认证依据。",
    }
