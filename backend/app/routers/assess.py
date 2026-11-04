"""
app/routers/assess.py — 可靠性评估的接口

【这个模块做什么】
围绕"一次评估"的全部查询与重算：
    POST /projects/{id}/assess                 发起评估（落库）
    GET  /assessments/{id}                     取完整结果（含曲线、短板、判定理由）
    GET  /assessments/{id}/items               逐零件明细（分页）
    GET  /assessments/{id}/trace/{item_id}     单个零件的计算追溯
    GET  /assessments/{id}/wear                磨损寿命排行榜
    GET  /assessments/{id}/derating            降额检查结果
    POST /assessments/{id}/sensitivity         敏感性扫描
    GET  /assessments/{id}/compare-standards   双标准对比
    GET  /assessments/compare?ids=1,2          两次评估横向对比（两个 BOM / 两个方案）

【为什么"双标准对比"要基于同一次评估重算而不是调两次评估接口】
两次独立调用之间，参数库可能被改、BOM 可能被改，对比就没有意义了。
这里从同一条 assessment 的 assumptions 快照出发重算，保证除"标准"外其他条件完全一致。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.calc import compare_standards as core_compare
from core.models import Assumption
from core.sens import sweep as sens_sweep
from core.standards.loader import load_param_set

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import (
    Assessment,
    AssessmentItem,
    BomVersion,
    DeratingResultRow,
    Project,
    SensitivityRun,
    User,
    WearResultRow,
)
from ..schemas import AssessRequest, AssumptionIn, SensitivityRequest
from ..services import assess as assess_service
from ..services import bom as bom_service
from ..services import classify as classify_service

router = APIRouter(tags=["评估"])


def _get_assessment(db: Session, aid: int, user: User) -> Assessment:
    a = db.get(Assessment, aid)
    if not a:
        raise HTTPException(status_code=404, detail="评估记录不存在")
    p = db.get(Project, a.project_id)
    if p and user.role != "admin" and p.owner_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")
    return a


def _assumption_of(record: Assessment) -> AssumptionIn:
    data = json.loads(record.assumptions_json or "{}")
    data.setdefault("standard", record.standard)
    data.setdefault("mode", record.mode)
    return AssumptionIn(**{k: v for k, v in data.items() if k in AssumptionIn.model_fields})


@router.post("/projects/{project_id}/assess")
def run_assessment(
    project_id: int,
    body: AssessRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if user.role != "admin" and project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作该项目")

    vid = body.bom_version_id or project.current_bom_version_id
    if not vid:
        raise HTTPException(status_code=400, detail="该项目还没有 BOM，请先导入或生成")
    version = db.get(BomVersion, vid)
    if not version:
        raise HTTPException(status_code=404, detail="BOM 版本不存在")

    # 未完成分类时给出明确的、可操作的中文提示，而不是一个 500
    try:
        record, payload = assess_service.run(
            db, project, version, body.assumption, user,
            with_sensitivity=body.with_sensitivity, note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # 计算核心的 ParamError / CalcError 等
        raise HTTPException(status_code=400, detail=f"计算失败：{e}")

    project.status = "assessed"
    db.commit()
    return {"assessment": assess_service.summary(record), "result": payload}


@router.get("/assessments/{assessment_id}")
def get_assessment(assessment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    record = _get_assessment(db, assessment_id, user)
    payload = assess_service.load_result(db, record)
    payload["meta"] = assess_service.summary(record)
    payload["param_meta"] = assess_service.param_meta(record.standard)
    return payload


@router.get("/assessments/{assessment_id}/items")
def list_items(
    assessment_id: int,
    page: int = 1,
    page_size: int = 50,
    order: str = Query(default="lambda", pattern="^(lambda|qty|line)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_assessment(db, assessment_id, user)
    q = db.query(AssessmentItem).filter(AssessmentItem.assessment_id == assessment_id)
    if order == "lambda":
        q = q.order_by(AssessmentItem.lambda_part.desc())
    elif order == "qty":
        q = q.order_by(AssessmentItem.qty.desc())
    else:
        q = q.order_by(AssessmentItem.id)
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "bom_item_id": r.bom_item_id,
                "part_number": r.part_number,
                "category_code": r.category_code,
                "category_name": r.category_name,
                "qty": r.qty,
                "lambda_b": r.lambda_b,
                "factors": json.loads(r.factors_json or "{}"),
                "lambda_part": r.lambda_part,
                "contribution_pct": r.contribution_pct,
            }
            for r in rows
        ],
    }


@router.get("/assessments/{assessment_id}/trace/{bom_item_id}")
def get_trace(
    assessment_id: int,
    bom_item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_assessment(db, assessment_id, user)
    r = (
        db.query(AssessmentItem)
        .filter(AssessmentItem.assessment_id == assessment_id, AssessmentItem.bom_item_id == bom_item_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="该评估中没有这个零件")
    return {
        "part_number": r.part_number,
        "category_name": r.category_name,
        "qty": r.qty,
        "lambda_b": r.lambda_b,
        "factors": json.loads(r.factors_json or "{}"),
        "lambda_part": r.lambda_part,
        "trace": json.loads(r.trace_json or "[]"),
    }


@router.get("/assessments/{assessment_id}/wear")
def get_wear(assessment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    record = _get_assessment(db, assessment_id, user)
    payload = json.loads(record.result_json or "{}")
    return payload.get("wear", {})


@router.get("/assessments/{assessment_id}/derating")
def get_derating(assessment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    record = _get_assessment(db, assessment_id, user)
    payload = json.loads(record.result_json or "{}")
    return payload.get("derating", {})


@router.post("/assessments/{assessment_id}/sensitivity")
def run_sensitivity(
    assessment_id: int,
    body: SensitivityRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    record = _get_assessment(db, assessment_id, user)
    version = db.get(BomVersion, record.bom_version_id)
    if not version:
        raise HTTPException(status_code=404, detail="BOM 版本已不存在")
    parts = bom_service.items_to_part_inputs(db, version.id)

    assumption_in = _assumption_of(record)
    assumption = assess_service.to_core_assumption(assumption_in)
    params = load_param_set(assumption.standard, str(settings.param_dir))

    values = body.values
    if body.variable in ("quality_level", "environment") and values:
        values = [str(v) for v in values]
    elif body.variable in ("ambient_temp", "duty_cycle") and values:
        values = [float(v) for v in values]

    result = sens_sweep.sweep(parts, assumption, params, body.variable, values)

    db.add(
        SensitivityRun(
            assessment_id=record.id,
            variable=result.variable,
            sweep_json=json.dumps(assess_service_json(result), ensure_ascii=False),
            elasticity=result.elasticity,
            note=result.conclusion,
        )
    )
    db.commit()

    return {
        "variable": result.variable,
        "variable_label": result.variable_label,
        "x_unit": result.x_unit,
        "elasticity": result.elasticity,
        "total_swing_pct": result.total_swing_pct,
        "conclusion": result.conclusion,
        "points": [{"x": p.x, "label": p.label, "mtbf_hours": p.mtbf_hours, "lambda_total_fit": p.lambda_total_fit} for p in result.points],
        "ranking": sens_sweep.rank_assumptions(parts, assumption, params),
    }


def assess_service_json(result) -> Dict[str, Any]:
    from core.calc import to_dict

    return to_dict(result)


@router.get("/assessments/{assessment_id}/compare-standards")
def compare_standards(assessment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    record = _get_assessment(db, assessment_id, user)
    version = db.get(BomVersion, record.bom_version_id)
    if not version:
        raise HTTPException(status_code=404, detail="BOM 版本已不存在")
    parts = bom_service.items_to_part_inputs(db, version.id)
    assumption = assess_service.to_core_assumption(_assumption_of(record))
    return core_compare(parts, assumption, str(settings.param_dir))


@router.get("/assessments/compare")
def compare_two(
    ids: str = Query(..., description="两个评估 id，逗号分隔，如 3,7"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids 格式应为 3,7")
    if len(id_list) != 2:
        raise HTTPException(status_code=400, detail="请提供两个评估 id")

    records = [_get_assessment(db, i, user) for i in id_list]
    out = []
    for r in records:
        payload = json.loads(r.result_json or "{}")
        a = payload.get("assessment", {})
        out.append(
            {
                "assessment": assess_service.summary(r),
                "bom_version_id": r.bom_version_id,
                "lambda_total_fit": r.lambda_total_fit,
                "mtbf_hours": r.mtbf_hours,
                "r_at_target": r.r_at_target,
                "verdict": r.verdict,
                "top_contributors": a.get("top_contributors", [])[:8],
                "wear": (payload.get("wear", {}) or {}).get("items", [])[:5],
            }
        )

    a0, a1 = out
    delta = {
        "mtbf_change_pct": (
            round((a1["mtbf_hours"] - a0["mtbf_hours"]) / a0["mtbf_hours"] * 100, 2)
            if a0["mtbf_hours"] and a1["mtbf_hours"]
            else None
        ),
        "r_change_pp": round((a1["r_at_target"] - a0["r_at_target"]) * 100, 2),
        "verdict_change": f"{a0['verdict']} → {a1['verdict']}",
    }
    return {"left": a0, "right": a1, "delta": delta}


@router.get("/assessments")
def list_assessments(
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Assessment)
    if project_id:
        p = db.get(Project, project_id)
        if p and user.role != "admin" and p.owner_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问")
        q = q.filter(Assessment.project_id == project_id)
    elif user.role != "admin":
        mine = [p.id for p in db.query(Project).filter(Project.owner_id == user.id).all()]
        q = q.filter(Assessment.project_id.in_(mine or [-1]))
    rows = q.order_by(Assessment.created_at.desc()).limit(100).all()
    return [assess_service.summary(r) for r in rows]
