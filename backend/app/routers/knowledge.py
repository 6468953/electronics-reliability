"""
app/routers/knowledge.py — 分类知识库维护

【这个模块做什么】
类目与关键词的增删改查。这是"知识库可维护"的落地点：
    · 新增类目（遇到库里没有的器件类型，例如"超级电容"）
    · 编辑关键词与权重（发现某类总是误判，就是关键词写少了/权重不够）
    · 禁用关键词（自动学习学歪了，可以关掉它而不必物理删除）

【为什么关键词表要分 source】
seed（种子）/ learned（自动学）/ manual（人工加）三种来源要能分辨：
出现误判时，第一件事就是看是哪个来源的词在起作用。自动学习的词默认权重低，
就是为了不让人工维护的知识被机器覆盖。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, log_action, require_admin
from ..models import Category, CategoryKeyword, User
from ..schemas import CategoryCreate, CategoryUpdate, KeywordCreate, KeywordUpdate

router = APIRouter(tags=["知识库"])


def _cat_dict(c: Category, with_keywords: bool = False) -> Dict[str, Any]:
    d = {
        "id": c.id,
        "code": c.code,
        "name": c.name,
        "parent_code": c.parent_code,
        "level": c.level,
        "description": c.description,
        "aliases": json.loads(c.aliases_json or "[]"),
        "samples": json.loads(c.samples_json or "[]"),
        "is_active": c.is_active,
        "keyword_count": sum(1 for k in c.keywords if k.is_active and not k.is_negative),
        "negative_count": sum(1 for k in c.keywords if k.is_active and k.is_negative),
    }
    if with_keywords:
        d["keywords"] = [
            {
                "id": k.id,
                "keyword": k.keyword,
                "weight": k.weight,
                "is_negative": k.is_negative,
                "source": k.source,
                "hit_count": k.hit_count,
                "is_active": k.is_active,
            }
            for k in sorted(c.keywords, key=lambda x: (x.is_negative, -x.weight))
        ]
    return d


@router.get("/categories")
def list_categories(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cats = db.query(Category).order_by(Category.level, Category.sort_order, Category.id).all()
    majors = [c for c in cats if c.level == 1]
    subs = [c for c in cats if c.level == 2]

    tree = []
    for m in majors:
        children = [c for c in subs if c.parent_code == m.code]
        tree.append(
            {
                **_cat_dict(m),
                "children": [
                    {
                        **_cat_dict(c),
                        "usage": 0,  # 用量统计在前端按需查，避免这里做 N 次 count
                    }
                    for c in children
                ],
            }
        )
    orphans = [c for c in subs if not any(x.code == c.parent_code for x in majors)]
    return {"tree": tree, "orphans": [_cat_dict(c) for c in orphans], "total": len(cats)}


@router.get("/categories/{code}")
def get_category(code: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    c = db.query(Category).filter(Category.code == code).first()
    if not c:
        raise HTTPException(status_code=404, detail="类目不存在")
    return _cat_dict(c, with_keywords=True)


@router.post("/categories", status_code=201)
def create_category(
    body: CategoryCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if db.query(Category).filter(Category.code == body.code).first():
        raise HTTPException(status_code=400, detail="类目编码已存在")
    if body.parent_code and not db.query(Category).filter(Category.code == body.parent_code).first():
        raise HTTPException(status_code=400, detail="父类目不存在")

    max_order = db.query(Category).count()
    c = Category(
        code=body.code,
        name=body.name,
        parent_code=body.parent_code,
        level=2 if body.parent_code else 1,
        description=body.description,
        aliases_json=json.dumps(body.aliases, ensure_ascii=False),
        samples_json=json.dumps(body.samples, ensure_ascii=False),
        sort_order=max_order,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    log_action(db, admin, "create_category", "category", c.id, c.code)
    return _cat_dict(c)


@router.patch("/categories/{code}")
def update_category(
    code: str,
    body: CategoryUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    c = db.query(Category).filter(Category.code == code).first()
    if not c:
        raise HTTPException(status_code=404, detail="类目不存在")
    data = body.model_dump(exclude_unset=True)
    if "aliases" in data and data["aliases"] is not None:
        c.aliases_json = json.dumps(data.pop("aliases"), ensure_ascii=False)
    if "samples" in data and data["samples"] is not None:
        c.samples_json = json.dumps(data.pop("samples"), ensure_ascii=False)
    for k, v in data.items():
        setattr(c, k, v)
    db.commit()
    log_action(db, admin, "update_category", "category", c.id, c.code)
    return _cat_dict(c, with_keywords=True)


@router.delete("/categories/{code}", status_code=204)
def delete_category(code: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    c = db.query(Category).filter(Category.code == code).first()
    if not c:
        raise HTTPException(status_code=404, detail="类目不存在")
    # 有 BOM 行在用就不许删——删了历史评估的分类就悬空了
    from ..models import BomItem

    used = db.query(BomItem).filter(BomItem.category_id == c.id).count()
    if used:
        raise HTTPException(status_code=400, detail=f"该类目已被 {used} 行 BOM 使用，请先停用（is_active=false）而不是删除")
    db.delete(c)
    db.commit()
    log_action(db, admin, "delete_category", "category", c.id, code)
    return None


@router.get("/categories/{code}/keywords")
def list_keywords(code: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    c = db.query(Category).filter(Category.code == code).first()
    if not c:
        raise HTTPException(status_code=404, detail="类目不存在")
    return [
        {
            "id": k.id,
            "keyword": k.keyword,
            "weight": k.weight,
            "is_negative": k.is_negative,
            "source": k.source,
            "hit_count": k.hit_count,
            "is_active": k.is_active,
        }
        for k in c.keywords
    ]


@router.post("/categories/{code}/keywords", status_code=201)
def add_keyword(
    code: str,
    body: KeywordCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    c = db.query(Category).filter(Category.code == code).first()
    if not c:
        raise HTTPException(status_code=404, detail="类目不存在")
    exists = (
        db.query(CategoryKeyword)
        .filter(
            CategoryKeyword.category_id == c.id,
            CategoryKeyword.keyword == body.keyword,
            CategoryKeyword.is_negative.is_(body.is_negative),
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="该关键词已存在")

    k = CategoryKeyword(
        category_id=c.id,
        keyword=body.keyword,
        weight=body.weight,
        is_negative=body.is_negative,
        source="manual",
    )
    db.add(k)
    db.commit()
    db.refresh(k)
    log_action(db, admin, "add_keyword", "category", c.id, f"{body.keyword} w={body.weight}")
    return {"id": k.id, "keyword": k.keyword, "weight": k.weight, "is_negative": k.is_negative}


@router.patch("/keywords/{kw_id}")
def update_keyword(
    kw_id: int,
    body: KeywordUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    k = db.get(CategoryKeyword, kw_id)
    if not k:
        raise HTTPException(status_code=404, detail="关键词不存在")
    data = body.model_dump(exclude_unset=True)
    for key, v in data.items():
        if v is not None:
            setattr(k, key, v)
    db.commit()
    return {"id": k.id, "weight": k.weight, "is_active": k.is_active}


@router.delete("/keywords/{kw_id}", status_code=204)
def delete_keyword(kw_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    k = db.get(CategoryKeyword, kw_id)
    if not k:
        raise HTTPException(status_code=404, detail="关键词不存在")
    db.delete(k)
    db.commit()
    log_action(db, admin, "delete_keyword", "keyword", kw_id, k.keyword)
    return None
