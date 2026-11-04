"""
app/routers/classify.py — 分类匹配、人工确认队列、统计看板

【这个模块做什么】
让"机器先分、人再核"这条链路可用：
    POST /bom/versions/{vid}/classify          重新跑分类
    GET  /bom/versions/{vid}/queue             待确认队列（含候选与理由）
    POST /bom/items/{iid}/confirm              单条确认（可应用到相似行 + 沉淀知识库）
    POST /bom/versions/{vid}/confirm-batch     批量确认（同一类目的多行一次搞定）
    GET  /bom/versions/{vid}/stats             统计看板数据

【批量确认的业务意义】
真实 BOM 里"贴片电阻 10K 0603"可能重复 30 行（不同位号）。逐行确认是折磨，
所以批量接口按 item_ids 一次写库，并且只学一次（避免同一描述反复学同样的词）。
"""

from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, log_action
from ..models import BomItem, BomVersion, ClassifyFeedback, Project, User
from ..schemas import ClassifyBatchConfirm, ClassifyConfirm
from ..services import classify as classify_service
from ..services.classify import stats as classify_stats
from ..services import kb as kb_service
from ..services.kb import code_to_id

router = APIRouter(tags=["分类"])


def _version(db: Session, vid: int, user: User) -> BomVersion:
    v = db.get(BomVersion, vid)
    if not v:
        raise HTTPException(status_code=404, detail="BOM 版本不存在")
    p = db.get(Project, v.project_id)
    if p and user.role != "admin" and p.owner_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")
    return v


@router.post("/bom/versions/{version_id}/classify")
def run_classify(
    version_id: int,
    only_unclassified: bool = Query(default=False, description="只处理未确认的行"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    v = _version(db, version_id, user)
    result = classify_service.run_classification(db, v, only_unclassified=only_unclassified)

    project = db.get(Project, v.project_id)
    if project and project.status in ("draft", "bom_ready"):
        project.status = "classified"
        db.commit()

    log_action(db, user, "classify", "bom_version", v.id, json.dumps(result, ensure_ascii=False))
    return result


@router.get("/bom/versions/{version_id}/queue")
def review_queue(
    version_id: int,
    status: Optional[str] = Query(default=None, description="不传=全部待处理（pending_review + unrecognized）"),
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    v = _version(db, version_id, user)
    q = db.query(BomItem).filter(BomItem.bom_version_id == v.id)
    if status:
        q = q.filter(BomItem.match_status == status)
    else:
        q = q.filter(BomItem.match_status.in_(["pending_review", "unrecognized", "unclassified"]))

    total = q.count()
    # 未识别的排前面（更需要人看），同状态内按相似度降序
    rows = (
        q.order_by(
            BomItem.match_status.desc(),
            BomItem.line_no,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for i in rows:
        cands = []
        try:
            cands = json.loads(i.candidate_json or "[]")
        except json.JSONDecodeError:
            pass
        items.append(
            {
                "id": i.id,
                "line_no": i.line_no,
                "part_number": i.part_number,
                "description": i.description,
                "qty": i.qty,
                "match_status": i.match_status,
                "match_score": i.match_score,
                "match_reason": i.match_reason,
                "candidates": cands,
            }
        )
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post("/bom/items/{item_id}/confirm")
def confirm(
    item_id: int,
    body: ClassifyConfirm,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = db.get(BomItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="零件行不存在")
    _version(db, item.bom_version_id, user)

    cands = json.loads(item.candidate_json or "[]")
    suggested = cands[0].get("category_code", "") if cands else ""

    try:
        result, learned = classify_service.confirm_item(
            db,
            item,
            body.category_code,
            user,
            learn=body.learn,
            apply_to_similar=body.apply_to_similar,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    db.add(
        ClassifyFeedback(
            bom_item_id=item.id,
            description=item.description,
            suggested_code=suggested,
            final_code=body.category_code,
            match_score=item.match_score,
            accepted=(suggested == body.category_code),
            learned_keywords=json.dumps(learned, ensure_ascii=False),
            operator_id=user.id,
        )
    )
    db.commit()

    log_action(db, user, "confirm_category", "bom_item", item.id, f"{suggested} → {body.category_code}")
    return {**result, "learned_keywords": learned, "suggested_code": suggested}


@router.post("/bom/versions/{version_id}/confirm-batch")
def confirm_batch(
    version_id: int,
    body: ClassifyBatchConfirm,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    v = _version(db, version_id, user)
    if not body.item_ids:
        raise HTTPException(status_code=400, detail="item_ids 不能为空")

    code2id = code_to_id(db)
    if body.category_code not in code2id:
        raise HTTPException(status_code=400, detail="类目不存在")
    cat_id = code2id[body.category_code]

    items = (
        db.query(BomItem)
        .filter(BomItem.bom_version_id == v.id, BomItem.id.in_(body.item_ids))
        .all()
    )
    if not items:
        raise HTTPException(status_code=404, detail="没有匹配的零件行")

    learned_all: List[str] = []
    from datetime import datetime

    for i in items:
        cands = json.loads(i.candidate_json or "[]")
        suggested = cands[0].get("category_code", "") if cands else ""
        i.category_id = cat_id
        i.match_status = "confirmed"
        i.category_source = "manual"
        i.confirmed_by = user.id
        i.confirmed_at = datetime.now()

        db.add(
            ClassifyFeedback(
                bom_item_id=i.id,
                description=i.description,
                suggested_code=suggested,
                final_code=body.category_code,
                match_score=i.match_score,
                accepted=(suggested == body.category_code),
                learned_keywords="[]",
                operator_id=user.id,
            )
        )
        if body.learn and suggested and suggested != body.category_code:
            learned_all.extend(kb_service.learn_from_correction(db, i.description, body.category_code, suggested))

    db.commit()
    log_action(db, user, "confirm_category_batch", "bom_version", v.id, f"{len(items)} 行 → {body.category_code}")
    return {"confirmed": len(items), "category_code": body.category_code, "learned_keywords": list(dict.fromkeys(learned_all))}


@router.get("/bom/versions/{version_id}/stats")
def stats(version_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    v = _version(db, version_id, user)
    return classify_stats(db, v)


@router.get("/classify/feedback")
def recent_feedback(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """最近的人工确认记录：用于展示"引擎学得怎么样"。"""
    rows = db.query(ClassifyFeedback).order_by(ClassifyFeedback.id.desc()).limit(limit).all()
    total = db.query(ClassifyFeedback).count()
    accepted = db.query(ClassifyFeedback).filter(ClassifyFeedback.accepted.is_(True)).count()
    return {
        "total": total,
        "accepted": accepted,
        "accept_rate": round(accepted / total * 100, 1) if total else 0.0,
        "items": [
            {
                "id": r.id,
                "description": r.description,
                "suggested_code": r.suggested_code,
                "final_code": r.final_code,
                "accepted": r.accepted,
                "match_score": r.match_score,
                "learned_keywords": json.loads(r.learned_keywords or "[]"),
                "created_at": r.created_at.isoformat(timespec="seconds"),
            }
            for r in rows
        ],
    }
