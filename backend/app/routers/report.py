"""
app/routers/report.py — 报告生成、历史与下载

【这个模块做什么】
    POST /assessments/{id}/report    生成 PDF 或 XLSX
    GET  /reports                    报告列表（按项目过滤）
    GET  /reports/{id}/download      下载

【为什么不缓存复用旧文件】
参数库、BOM、知识库都可能变。每次"生成"都重新渲染，并在报告里写清 param_version /
engine_version，才是真正的可复现。历史文件保留在 data/reports 下，供下载与比对。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from pathlib import Path

from ..config import settings
from ..db import get_db
from ..deps import get_current_user, log_action
from ..models import Assessment, Project, Report, User
from ..schemas import ReportRequest
from ..services import report as report_service

router = APIRouter(tags=["报告"])


def _assessment(db: Session, aid: int, user: User) -> Assessment:
    a = db.get(Assessment, aid)
    if not a:
        raise HTTPException(status_code=404, detail="评估记录不存在")
    p = db.get(Project, a.project_id)
    if p and user.role != "admin" and p.owner_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")
    return a


@router.post("/assessments/{assessment_id}/report")
def create_report(
    assessment_id: int,
    body: ReportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    record = _assessment(db, assessment_id, user)
    try:
        path = report_service.generate(db, record, kind=body.kind)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"报告生成失败：{e}")

    size = path.stat().st_size if path.exists() else 0
    r = Report(
        project_id=record.project_id,
        assessment_id=record.id,
        kind=body.kind,
        file_path=str(path),
        file_size=size,
        verdict=record.verdict,
        generated_by=user.id,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    log_action(db, user, "generate_report", "report", r.id, f"{body.kind} {size/1024:.0f}KB")

    return {
        "id": r.id,
        "kind": r.kind,
        "file_size": r.file_size,
        "verdict": r.verdict,
        "created_at": r.created_at.isoformat(timespec="seconds"),
        "download_url": f"{settings.api_prefix}/reports/{r.id}/download",
    }


@router.get("/reports")
def list_reports(
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Report)
    if project_id:
        p = db.get(Project, project_id)
        if p and user.role != "admin" and p.owner_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问")
        q = q.filter(Report.project_id == project_id)
    elif user.role != "admin":
        mine = [p.id for p in db.query(Project).filter(Project.owner_id == user.id).all()]
        q = q.filter(Report.project_id.in_(mine or [-1]))

    rows = q.order_by(Report.id.desc()).limit(200).all()
    return [
        {
            "id": r.id,
            "project_id": r.project_id,
            "assessment_id": r.assessment_id,
            "kind": r.kind,
            "file_size": r.file_size,
            "verdict": r.verdict,
            "created_at": r.created_at.isoformat(timespec="seconds"),
            "exists": Path(r.file_path).exists() if r.file_path else False,
            "download_url": f"{settings.api_prefix}/reports/{r.id}/download",
        }
        for r in rows
    ]


@router.get("/reports/{report_id}/download")
def download(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = db.get(Report, report_id)
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")
    p = db.get(Project, r.project_id)
    if p and user.role != "admin" and p.owner_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")

    path = Path(r.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告文件已被清理，请重新生成")

    media = (
        "application/pdf" if r.kind == "pdf"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    filename = f"可靠性评估报告_{r.created_at.strftime('%Y%m%d')}_{r.id}.{r.kind}"
    return FileResponse(path, media_type=media, filename=filename)
