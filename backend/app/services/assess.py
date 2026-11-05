"""
app/services/assess.py — 执行评估并持久化

【这个模块做什么】
把"页面上的一次点击"变成一份可查、可复现的评估记录：
    取 BOM 行 → 转 PartInput → 调计算核心 → 落库（汇总 + 逐零件 + 磨损 + 降额 + 敏感性）

【为什么计算结果要整份存下来】
参数库会升级、知识库会被改、BOM 也可能改。如果历史评估每次都用"当前参数"重算，
昨天 PASS 的报告明天可能变 FAIL，报告就没法作为交付物。
所以这里存两样东西：
    · assumptions_json：当时的全部假设（含四参数、duty、目标、标准、模式）
    · result_json：当时的完整结果
并记录 param_version / engine_version。复现的口径就齐了。

【落库体积的取舍】
逐零件的 trace（计算明细）可能很长（1000 行 × 5 步），所以：
    · 汇总 payload 里【剥掉】trace，避免一列 JSON 膨胀到几 MB；
    · trace 落到 assessment_items，按需单条查询（前端点开某一行才拉）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from core.calc import evaluate as core_evaluate
from core.models import Assumption
from core.standards.loader import load_param_set

from ..config import settings
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
from ..schemas import AssumptionIn
from . import bom as bom_service


def to_core_assumption(a: AssumptionIn) -> Assumption:
    """页面假设 → 计算核心假设。

    唯一的换算：页面按"日通电小时"输入（工程师的思维习惯），核心按"占比"计算
    （因为 R(t) 折算要用比例）。这个换算是本系统最常见的口径错源，所以放在一处并注释。
    """
    return Assumption(
        environment=a.environment,
        ambient_temp_c=a.ambient_temp_c,
        quality_level=a.quality_level,
        duty_cycle=max(0.01, min(1.0, a.duty_hours_per_day / 24.0)),
        target_years=a.target_years,
        target_survival=a.target_survival,
        mtbf_threshold_hours=a.mtbf_threshold_hours,
        standard=a.standard,
        mode=a.mode,
    )


def run(
    db: Session,
    project: Project,
    version: BomVersion,
    assumption_in: AssumptionIn,
    user: Optional[User],
    *,
    with_sensitivity: bool = True,
    note: str = "",
    compare_group_id: Optional[str] = None,
) -> Tuple[Assessment, Dict[str, Any]]:
    parts = bom_service.items_to_part_inputs(db, version.id)
    assumption = to_core_assumption(assumption_in)

    payload = core_evaluate(
        parts,
        assumption,
        with_wear=True,
        with_derating=True,
        with_sensitivity=with_sensitivity,
        param_dir=str(settings.param_dir),
    )

    a = payload["assessment"]
    record = Assessment(
        project_id=project.id,
        bom_version_id=version.id,
        standard=assumption.standard,
        mode=assumption.mode,
        assumptions_json=json.dumps(
            {**assumption_in.model_dump(), "duty_cycle": assumption.duty_cycle}, ensure_ascii=False
        ),
        result_json="{}",   # 下面 strip 后回填
        param_version=a["param_version"],
        engine_version=a["engine_version"],
        lambda_total_fit=float(a["lambda_total_fit"]),
        mtbf_hours=float(a["mtbf_hours"]) if a["mtbf_hours"] not in (None, "Infinity") else None,
        r_at_target=float(a["r_at_target"]),
        verdict=a["verdict"],
        compare_group_id=compare_group_id,
        note=note,
        created_by=user.id if user else None,
    )
    db.add(record)
    db.flush()

    # ---- 逐零件（含 trace）----
    contrib = {row["part_id"]: row["contribution_pct"] for row in a["top_contributors"]}
    # top_contributors 只保留 Top10，其余零件的占比要么从总和补，要么重新算。
    total_lambda = float(a["lambda_total_fit"]) or 1.0
    for p in a["parts"]:
        pct = contrib.get(p["part_id"])
        if pct is None:
            pct = round(p["lambda_part"] / total_lambda * 100.0, 3)
        db.add(
            AssessmentItem(
                assessment_id=record.id,
                bom_item_id=p["part_id"],
                part_number=p["part_number"],
                category_code=p["category_code"],
                category_name=p["category_name"],
                qty=p["qty"],
                lambda_b=float(p["lambda_b"]),
                factors_json=json.dumps(p["factors"], ensure_ascii=False),
                lambda_part=float(p["lambda_part"]),
                contribution_pct=float(pct),
                trace_json=json.dumps(p["trace"], ensure_ascii=False),
            )
        )

    # ---- 磨损 ----
    for w in payload.get("wear", {}).get("items", []):
        db.add(
            WearResultRow(
                assessment_id=record.id,
                bom_item_id=w["part_id"],
                part_number=w["part_number"],
                mechanism=w["mechanism"],
                mechanism_label=w["mechanism_label"],
                life_hours=w["life_hours"],
                life_years=w["life_years"],
                formula=w["formula"],
                inputs_json=json.dumps(w["inputs"], ensure_ascii=False),
                using_defaults_json=json.dumps(w["using_defaults"], ensure_ascii=False),
                is_limiting=bool(w["is_limiting"]),
            )
        )

    # ---- 降额 ----
    for d in payload.get("derating", {}).get("items", []):
        db.add(
            DeratingResultRow(
                assessment_id=record.id,
                bom_item_id=d["part_id"],
                part_number=d["part_number"],
                category_code=d["category_code"],
                stress_type=d["stress_type"],
                rated_value=d["rated_value"],
                applied_value=d["applied_value"],
                ratio=d["ratio"],
                max_ratio=d["max_ratio"],
                verdict=d["verdict"],
                note=d["note"],
            )
        )

    # ---- 敏感性 ----
    sens = payload.get("sensitivity", {}).get("temp")
    if sens:
        db.add(
            SensitivityRun(
                assessment_id=record.id,
                variable=sens["variable"],
                sweep_json=json.dumps(sens, ensure_ascii=False),
                elasticity=sens.get("elasticity"),
                note=sens.get("conclusion", ""),
            )
        )

    # ---- 汇总结果（剥掉 trace 后回填，控制单列体积）----
    slim = _strip_traces(payload)
    record.result_json = json.dumps(slim, ensure_ascii=False)
    db.commit()
    db.refresh(record)
    return record, payload


def _strip_traces(payload: Dict[str, Any]) -> Dict[str, Any]:
    slim = json.loads(json.dumps(payload, ensure_ascii=False))
    for p in slim.get("assessment", {}).get("parts", []):
        p.pop("trace", None)
    return slim


def load_result(db: Session, record: Assessment) -> Dict[str, Any]:
    """取回完整结果（含各零件 trace，从 assessment_items 补回来）。"""
    payload = json.loads(record.result_json or "{}")
    items = (
        db.query(AssessmentItem)
        .filter(AssessmentItem.assessment_id == record.id)
        .order_by(AssessmentItem.lambda_part.desc())
        .all()
    )
    trace_map = {i.bom_item_id: json.loads(i.trace_json or "[]") for i in items}
    for p in payload.get("assessment", {}).get("parts", []):
        p["trace"] = trace_map.get(p["part_id"], [])
    return payload


def summary(record: Assessment) -> Dict[str, Any]:
    return {
        "id": record.id,
        "project_id": record.project_id,
        "bom_version_id": record.bom_version_id,
        "standard": record.standard,
        "mode": record.mode,
        "param_version": record.param_version,
        "engine_version": record.engine_version,
        "lambda_total_fit": record.lambda_total_fit,
        "mtbf_hours": record.mtbf_hours,
        "r_at_target": record.r_at_target,
        "verdict": record.verdict,
        "note": record.note,
        "created_at": record.created_at.isoformat(timespec="seconds"),
    }


def param_meta(standard: str) -> Dict[str, Any]:
    p = load_param_set(standard, str(settings.param_dir))
    return {
        "standard": p.standard,
        "version_tag": p.version_tag,
        "display_name": p.display_name,
        "source_ref": p.source_ref,
        "disclaimer": p.disclaimer,
        "data_quality": p.data_quality,
        "data_quality_note": p.data_quality_note,
        "notes": p.notes,
        "environments": [{"code": k, "label": v["label"], "mult": v["mult"]} for k, v in p.environments.items()],
        "quality_levels": [
            {"code": k, "label": v["label"], "pi_q": v["pi_q"]} for k, v in p.quality_levels.items()
        ],
        "category_count": len(p.categories),
        "confidence_factor_90": p.confidence_factor_90,
    }
