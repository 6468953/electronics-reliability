"""
app/services/classify.py — 分类业务流程

【这个模块做什么】
把"分类引擎（纯函数）"接到"数据库（有状态）"上：
  · run_classification：整份 BOM 跑一遍，落分类结果与候选；
  · confirm：人工确认/改判，写库并沉淀知识库；
  · apply_to_similar：一次确认应用到描述高度相似的多行（真实 BOM 里同一料号常有几十行）；
  · stats：分类统计看板的数据。

【一个容易做错的设计点：待确认行的 category_id 该不该填？】
本系统的处理是：
    auto            → 填 category_id，category_source=auto
    pending_review  → category_id 留空，候选存在 candidate_json 里
    unrecognized    → category_id 留空，无可靠候选
理由：如果待确认行也先"占一个"分类，评估时就会静默把它们算进去，用户以为已经核过了。
留空 + 评估前强制检查（items_to_part_inputs 会报错）才安全。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from core.classify.engine import Classifier

from ..models import BomItem, BomVersion, Category, Project, User
from . import kb as kb_service


def get_classifier(db: Session) -> Classifier:
    return Classifier(kb_service.build_kb(db))


def run_classification(db: Session, version: BomVersion, only_unclassified: bool = True) -> Dict[str, Any]:
    """对一份 BOM 跑自动分类。"""
    clf = get_classifier(db)
    code2id = kb_service.code_to_id(db)

    items = db.query(BomItem).filter(BomItem.bom_version_id == version.id).all()
    counts = {"auto": 0, "pending_review": 0, "unrecognized": 0, "skipped": 0}
    learned_hits: Dict[str, List[str]] = {}

    for item in items:
        if only_unclassified and item.category_id and item.category_source in ("manual", "learned"):
            counts["skipped"] += 1
            continue

        res = clf.classify(item.description)
        counts[res.status] = counts.get(res.status, 0) + 1

        item.match_status = res.status
        item.match_score = res.best.score if res.best else None
        item.match_reason = res.reason
        item.candidate_json = json.dumps([c.to_dict() for c in res.candidates], ensure_ascii=False)

        if res.status == "auto" and res.best:
            item.category_id = code2id.get(res.best.code)
            item.category_source = "auto"
            learned_hits.setdefault(res.best.code, []).extend(res.best.hits)
        else:
            # 待确认/未识别：不占分类，避免被静默计入评估
            if item.category_source != "manual":
                item.category_id = None
                item.category_source = ""

    db.commit()

    # 命中计数：用于知识库页面展示"哪些关键词真正在干活"
    for code, hits in learned_hits.items():
        kb_service.bump_hit_counts(db, code, hits)

    return {
        "total": len(items),
        **counts,
        "auto_pct": round(counts["auto"] / max(1, len(items)) * 100, 1),
    }


def confirm_item(
    db: Session,
    item: BomItem,
    category_code: str,
    user: Optional[User],
    learn: bool = True,
    apply_to_similar: bool = False,
    similar_threshold: float = 0.85,
) -> Tuple[Dict[str, Any], List[str]]:
    """确认一行分类。返回 (结果摘要, 学到的关键词)。"""
    cat = db.query(Category).filter(Category.code == category_code).first()
    if not cat:
        raise ValueError(f"类目 {category_code} 不存在")

    suggested = ""
    cands = json.loads(item.candidate_json or "[]")
    if cands:
        suggested = cands[0].get("category_code", "")

    item.category_id = cat.id
    item.category_source = "learned" if (learn and suggested and suggested != category_code) else "manual"
    item.match_status = "confirmed"
    item.confirmed_by = user.id if user else None
    from datetime import datetime

    item.confirmed_at = datetime.now()

    learned: List[str] = []
    if learn and suggested and suggested != category_code:
        learned = kb_service.learn_from_correction(db, item.description, category_code, suggested)

    applied = 0
    if apply_to_similar:
        # 只在"同一版本、尚未人工确认、描述高度相似"的行上扩散。
        # 阈值用字符相似度，而不是再跑一次分类——扩散的对象应该是"几乎一模一样"的行。
        from core.classify.similarity import char_containment
        from core.classify.normalize import normalize_text

        base = normalize_text(item.description)
        others = (
            db.query(BomItem)
            .filter(BomItem.bom_version_id == item.bom_version_id, BomItem.id != item.id)
            .filter(BomItem.category_source != "manual")
            .all()
        )
        for o in others:
            if char_containment(normalize_text(o.description), base) >= similar_threshold:
                o.category_id = cat.id
                o.category_source = "manual"
                o.match_status = "confirmed"
                o.confirmed_by = user.id if user else None
                o.confirmed_at = item.confirmed_at
                applied += 1

    db.commit()
    return (
        {
            "item_id": item.id,
            "category_code": cat.code,
            "category_name": cat.name,
            "applied_to_similar": applied,
        },
        learned,
    )


def stats(db: Session, version: BomVersion) -> Dict[str, Any]:
    items = db.query(BomItem).filter(BomItem.bom_version_id == version.id).all()
    status_count = {"auto": 0, "pending_review": 0, "unrecognized": 0, "confirmed": 0, "unclassified": 0}
    major_count: Dict[str, int] = {}
    major_name: Dict[str, str] = {}

    cats = {c.id: c for c in db.query(Category).all()}
    for c in cats.values():
        if c.level == 1:
            major_name[c.code] = c.name

    for it in items:
        status_count[it.match_status] = status_count.get(it.match_status, 0) + 1
        if it.category_id and it.category_id in cats:
            mc = cats[it.category_id].parent_code or "OTHER"
            major_count[mc] = major_count.get(mc, 0) + 1

    total = len(items) or 1
    confirmed_total = status_count.get("confirmed", 0) + status_count.get("auto", 0)
    return {
        "total": len(items),
        "status": status_count,
        "auto_pct": round(status_count.get("auto", 0) / total * 100, 1),
        "classified_pct": round(confirmed_total / total * 100, 1),
        "by_major": [
            {"code": k, "name": major_name.get(k, k), "count": v}
            for k, v in sorted(major_count.items(), key=lambda x: -x[1])
        ],
        "pending_total": status_count.get("pending_review", 0) + status_count.get("unrecognized", 0),
    }
