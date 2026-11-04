"""
app/services/kb.py — 分类知识库的读写

【这个模块做什么】
知识库存在数据库里（可在页面上维护），但分类引擎要的是内存里的纯数据结构。
本模块负责三件事：
  1. 首次启动时从 params/categories_v1.json 灌种子数据；
  2. 把数据库里的类目 + 关键词装配成 Classifier 认识的形式；
  3. 把人工改判的结果"沉淀"回关键词表（带防污染规则）。

【为什么知识库放数据库而不是继续读 JSON】
需求要求"知识库可维护：支持新增类目、编辑关键词"以及"确认结果沉淀回知识库"。
JSON 只读文件做不到运行时可改。JSON 退化为"种子/出厂默认"，数据库是运行时真身。

【防污染规则（很重要）】
自动学习最容易把库搞坏：一次误操作就写入一个乱七八糟的关键词，之后所有零件都被带偏。
所以这里设了三道闸：
  · 只接受长度 ≥2、非数字、非单位的词；
  · 每次最多加 2 个，权重从 2.0 起步（低于人工种子词的 3~5）；
  · 同一个词若已被标注为 learned 且命中数为 0，再次出现时不再重复加，改为权重 +0.5（上限 4）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from core.classify.engine import suggest_keywords
from core.standards.loader import CategoryDef, load_category_kb

from ..config import settings
from ..models import Category, CategoryKeyword


def seed_from_json(db: Session) -> int:
    """若知识库为空，从 JSON 种子文件导入。返回导入的类目数。"""
    if db.query(Category).count() > 0:
        return 0

    kb = load_category_kb(str(settings.param_dir))
    # 先建大类（level=1），再建小类，保证 parent 引用可解析
    for i, major in enumerate(kb["major_categories"]):
        db.add(
            Category(
                code=major["code"],
                parent_code="",
                name=major["name"],
                level=1,
                description=f"{major['name']}（大类）",
                sort_order=i,
            )
        )
    db.flush()

    majors: Dict[str, Category] = {
        c.code: c for c in db.query(Category).filter(Category.level == 1).all()
    }

    count = 0
    for i, c in enumerate(kb["categories"]):
        parent = majors.get(c.parent)
        cat = Category(
            code=c.code,
            parent_code=c.parent,
            name=c.name,
            level=2,
            description=c.description,
            aliases_json=json.dumps(c.aliases, ensure_ascii=False),
            samples_json=json.dumps(c.samples, ensure_ascii=False),
            sort_order=i,
        )
        db.add(cat)
        db.flush()
        for kw in c.keywords:
            db.add(
                CategoryKeyword(
                    category_id=cat.id,
                    keyword=str(kw.get("k", "")).strip(),
                    weight=float(kw.get("w", 2)),
                    is_negative=False,
                    source="seed",
                )
            )
        for neg in c.negatives:
            db.add(
                CategoryKeyword(
                    category_id=cat.id,
                    keyword=str(neg).strip(),
                    weight=1.0,
                    is_negative=True,
                    source="seed",
                )
            )
        count += 1

    db.commit()
    return count


def build_kb(db: Session) -> Dict[str, Any]:
    """装配成 Classifier 需要的结构。只取启用的类目与启用的关键词。"""
    cats = (
        db.query(Category)
        .filter(Category.is_active.is_(True))
        .order_by(Category.level, Category.sort_order)
        .all()
    )
    majors = [c for c in cats if c.level == 1]
    subcats = [c for c in cats if c.level == 2]

    defs: List[CategoryDef] = []
    for c in subcats:
        kws = [
            {"k": k.keyword, "w": k.weight}
            for k in c.keywords
            if k.is_active and not k.is_negative
        ]
        negs = [k.keyword for k in c.keywords if k.is_active and k.is_negative]
        defs.append(
            CategoryDef(
                code=c.code,
                parent=c.parent_code,
                name=c.name,
                aliases=json.loads(c.aliases_json or "[]"),
                description=c.description or "",
                keywords=kws,
                negatives=negs,
                samples=json.loads(c.samples_json or "[]"),
            )
        )

    return {
        "version_tag": "db",
        "major_categories": [{"code": m.code, "name": m.name} for m in majors],
        "categories": defs,
        "notes": {},
    }


def code_to_id(db: Session) -> Dict[str, int]:
    return {c.code: c.id for c in db.query(Category).all()}


def id_to_code(db: Session) -> Dict[int, str]:
    return {c.id: c.code for c in db.query(Category).all()}


def learn_from_correction(
    db: Session,
    description: str,
    final_code: str,
    suggested_code: Optional[str],
) -> List[str]:
    """把一次改判沉淀成关键词。返回实际新增/调整的词，便于界面回显"学到了什么"。"""
    if not suggested_code or suggested_code == final_code:
        return []

    kb = build_kb(db)
    advice = suggest_keywords(description, final_code, suggested_code, kb)
    target = db.query(Category).filter(Category.code == final_code).first()
    if target is None:
        return []

    learned: List[str] = []
    for word in advice.get("add", []):
        existing = (
            db.query(CategoryKeyword)
            .filter(
                CategoryKeyword.category_id == target.id,
                CategoryKeyword.keyword == word,
                CategoryKeyword.is_negative.is_(False),
            )
            .first()
        )
        if existing:
            # 同一词被反复确认 → 逐步加权，上限 4.0（避免自动学习压过人工种子词）
            if existing.weight < 4.0:
                existing.weight = min(4.0, existing.weight + 0.5)
                learned.append(f"{word}（权重提升至 {existing.weight:g}）")
            continue
        db.add(
            CategoryKeyword(
                category_id=target.id,
                keyword=word,
                weight=2.0,
                is_negative=False,
                source="learned",
            )
        )
        learned.append(word)

    for word in advice.get("negative", []):
        exists = (
            db.query(CategoryKeyword)
            .filter(
                CategoryKeyword.category_id == target.id,
                CategoryKeyword.keyword == word,
                CategoryKeyword.is_negative.is_(True),
            )
            .first()
        )
        if not exists:
            db.add(
                CategoryKeyword(
                    category_id=target.id,
                    keyword=word,
                    weight=1.0,
                    is_negative=True,
                    source="learned",
                )
            )
            learned.append(f"-{word}（排除词）")

    db.commit()
    return learned


def bump_hit_counts(db: Session, category_code: str, hits: List[str]) -> None:
    """关键词命中计数。用于"越用越准"的展示：谁在干活、谁从没命中过。"""
    if not hits:
        return
    cat = db.query(Category).filter(Category.code == category_code).first()
    if cat is None:
        return
    for word in hits:
        kw = (
            db.query(CategoryKeyword)
            .filter(
                CategoryKeyword.category_id == cat.id,
                CategoryKeyword.keyword == word,
                CategoryKeyword.is_negative.is_(False),
            )
            .first()
        )
        if kw:
            kw.hit_count += 1
    db.commit()
