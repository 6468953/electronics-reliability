"""
app/routers/bom.py — BOM 模板、导入、模拟生成与明细查询

【这个模块做什么】
    GET  /bom/template.xlsx            下载模板
    POST /projects/{id}/bom/upload     上传解析（Excel/CSV）
    POST /projects/{id}/bom/simulate   一键生成模拟 BOM
    GET  /bom/versions/{vid}/items     分页查询明细（可按状态/关键词过滤）
    PATCH /bom/items/{iid}             改用量/位号/应力/额定值/冗余组

【导入后为什么自动跑一次分类】
用户体验：上传完 BOM 看到的第一屏就应该是"哪些自动归好类了、哪些要人看一眼"，
而不是一个空白的待办列表。分类很快（1000 行 < 2 秒），没必要让用户多点一次按钮。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, log_action
from ..models import BomItem, BomVersion, Project, User
from ..schemas import BomItemUpdate, BomSimulateRequest
from ..services import bom as bom_service
from ..services import classify as classify_service
from ..services.classify import stats as classify_stats

router = APIRouter(tags=["BOM"])


def _get_version(db: Session, version_id: int, user: User) -> BomVersion:
    v = db.get(BomVersion, version_id)
    if not v:
        raise HTTPException(status_code=404, detail="BOM 版本不存在")
    p = db.get(Project, v.project_id)
    if p and user.role != "admin" and p.owner_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该 BOM")
    return v


def _item_dict(i: BomItem, code: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
    cands = []
    try:
        cands = json.loads(i.candidate_json or "[]")
    except json.JSONDecodeError:
        cands = []
    return {
        "id": i.id,
        "line_no": i.line_no,
        "part_number": i.part_number,
        "description": i.description,
        "qty": i.qty,
        "ref_des": i.ref_des,
        "category_code": code or "",
        "category_name": name or "",
        "category_source": i.category_source,
        "match_score": i.match_score,
        "match_status": i.match_status,
        "match_reason": i.match_reason,
        "candidates": cands,
        "rated": json.loads(i.rated_json or "{}"),
        "rated_source": i.rated_source,
        "stress": json.loads(i.stress_json or "{}"),
        "redundancy_group": i.redundancy_group,
        "redundancy_note": i.redundancy_note,
    }


@router.get("/bom/template.xlsx")
def download_template(_: User = Depends(get_current_user)):
    content = bom_service.build_template()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="bom_template.xlsx"'},
    )


@router.post("/projects/{project_id}/bom/upload")
async def upload_bom(
    project_id: int,
    file: UploadFile = File(...),
    label: str = Query(default="上传 BOM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if user.role != "admin" and project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作该项目")

    filename = file.filename or "upload.xlsx"
    if not filename.lower().endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .csv 文件（.xls 请另存为 .xlsx）")

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 20MB")

    rows, issues = bom_service.parse_upload(filename, content)
    if any(i.get("level") == "error" and i.get("code") in ("empty_file", "missing_column") for i in issues):
        # 结构性错误（找不到表头/缺必需列）直接拒绝，不给用户一个半残的版本
        raise HTTPException(status_code=400, detail=issues[0]["message"])

    version = bom_service.create_version(db, project.id, label, "upload", filename, rows, issues, user.id)
    project.current_bom_version_id = version.id
    project.status = "bom_ready"
    db.commit()

    cls = classify_service.run_classification(db, version)
    project.status = "classified"
    db.commit()

    log_action(db, user, "upload_bom", "bom_version", version.id, f"{filename} · {len(rows)} 行")
    return {
        "bom_version_id": version.id,
        "version_no": version.version_no,
        "row_count": version.row_count,
        "issues": issues,
        "classification": cls,
    }


@router.post("/projects/{project_id}/bom/simulate")
def simulate_bom(
    project_id: int,
    body: BomSimulateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if user.role != "admin" and project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作该项目")

    from sim.generator import generate

    rows = generate(
        scale=body.scale,
        seed=body.seed,
        include_cases=body.include_cases,
        include_dirty=body.include_dirty,
    )
    issues: List[Dict[str, Any]] = []
    if body.include_dirty:
        issues.append(
            {"level": "warn", "code": "dup_pn", "message": "模拟数据中预置了 1 条重复料号，用于演示校验提示", "line_no": None}
        )
        issues.append(
            {"level": "warn", "code": "qty_empty", "message": "模拟数据中预置了 1 条缺用量行，已按 1 处理", "line_no": None}
        )

    version = bom_service.create_version(
        db, project.id, body.label, "simulated", f"sim_{body.scale}_{body.seed}.csv", rows, issues, user.id
    )
    project.current_bom_version_id = version.id
    project.status = "bom_ready"
    db.commit()

    cls = classify_service.run_classification(db, version)
    project.status = "classified"
    db.commit()

    log_action(db, user, "simulate_bom", "bom_version", version.id, f"scale={body.scale}, seed={body.seed}")
    return {
        "bom_version_id": version.id,
        "version_no": version.version_no,
        "row_count": version.row_count,
        "issues": issues,
        "classification": cls,
    }


@router.get("/bom/versions/{version_id}")
def get_version(version_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    v = _get_version(db, version_id, user)
    issues = []
    try:
        issues = json.loads(v.parse_warnings_json or "[]")
    except json.JSONDecodeError:
        pass
    return {
        "id": v.id,
        "project_id": v.project_id,
        "version_no": v.version_no,
        "label": v.label,
        "source": v.source,
        "filename": v.filename,
        "row_count": v.row_count,
        "qty_total": v.qty_total,
        "created_at": v.created_at.isoformat(timespec="seconds"),
        "issues": issues,
        "classification": classify_stats(db, v),
    }


@router.get("/bom/versions/{version_id}/items")
def list_items(
    version_id: int,
    status: Optional[str] = Query(default=None, description="auto/pending_review/unrecognized/confirmed/unclassified"),
    kw: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    v = _get_version(db, version_id, user)
    q = db.query(BomItem).filter(BomItem.bom_version_id == v.id)
    if status:
        q = q.filter(BomItem.match_status == status)
    if kw:
        like = f"%{kw}%"
        q = q.filter((BomItem.description.like(like)) | (BomItem.part_number.like(like)))

    total = q.count()
    rows = q.order_by(BomItem.line_no, BomItem.id).offset((page - 1) * page_size).limit(page_size).all()

    from ..models import Category

    cats = {c.id: c for c in db.query(Category).all()}
    items = []
    for i in rows:
        c = cats.get(i.category_id or -1)
        items.append(_item_dict(i, c.code if c else None, c.name if c else None))

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/bom/items/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    i = db.get(BomItem, item_id)
    if not i:
        raise HTTPException(status_code=404, detail="零件行不存在")
    _get_version(db, i.bom_version_id, user)
    from ..models import Category

    c = db.get(Category, i.category_id) if i.category_id else None
    d = _item_dict(i, c.code if c else None, c.name if c else None)
    # 附带解析预览：让用户知道"系统从描述里读到了什么"，这是判断降额/磨损结果是否可信的前提
    from core.parse_spec import merge_rated

    merged, sources = merge_rated(i.rated_json and json.loads(i.rated_json) or None, i.description)
    d["parsed_rated"] = merged
    d["parsed_sources"] = sources
    return d


@router.patch("/bom/items/{item_id}")
def update_item(
    item_id: int,
    body: BomItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    i = db.get(BomItem, item_id)
    if not i:
        raise HTTPException(status_code=404, detail="零件行不存在")
    v = _get_version(db, i.bom_version_id, user)

    data = body.model_dump(exclude_unset=True)
    if "qty" in data and data["qty"] is not None:
        if data["qty"] <= 0:
            raise HTTPException(status_code=400, detail="用量必须大于 0")
        i.qty = int(data["qty"])
    if "ref_des" in data and data["ref_des"] is not None:
        i.ref_des = data["ref_des"]
    if "description" in data and data["description"] is not None:
        i.description = data["description"]
        i.match_status = "unclassified"   # 描述变了，分类结果作废，需重新匹配
        i.category_id = None
        i.category_source = ""
    if "category_code" in data and data["category_code"]:
        from ..models import Category

        c = db.query(Category).filter(Category.code == data["category_code"]).first()
        if not c:
            raise HTTPException(status_code=400, detail="类目不存在")
        i.category_id = c.id
        i.category_source = "manual"
        i.match_status = "confirmed"
        i.confirmed_by = user.id
        from datetime import datetime

        i.confirmed_at = datetime.now()
    if "stress" in data and data["stress"] is not None:
        merged = json.loads(i.stress_json or "{}")
        merged.update({k: float(v) for k, v in data["stress"].items() if v is not None})
        i.stress_json = json.dumps(merged, ensure_ascii=False)
    if "rated" in data and data["rated"] is not None:
        merged = json.loads(i.rated_json or "{}")
        merged.update({k: float(v) for k, v in data["rated"].items() if v is not None})
        i.rated_json = json.dumps(merged, ensure_ascii=False)
        i.rated_source = "manual"
    if "redundancy_group" in data:
        i.redundancy_group = data["redundancy_group"] or None
    if "redundancy_note" in data and data["redundancy_note"] is not None:
        i.redundancy_note = data["redundancy_note"]

    db.commit()
    log_action(db, user, "update_bom_item", "bom_item", i.id, str(data)[:500])
    return {"item_id": i.id, "updated": list(data.keys()), "bom_version_id": v.id}
