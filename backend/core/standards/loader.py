"""
core/standards/loader.py — 参数库加载与合并

【这个模块做什么】
把 params/*.json 里的"标准参数表"读进内存，并做三件事：
  1. 把「因子族模板（family）」和「类别差异项」合并成每个类别完整的计算规格；
  2. 提供查表接口：λ_g(类别, 环境)、π_Q(质量等级)、环境倍率；
  3. 校验参数库自身的一致性（类别引用的 family 是否存在、必需字段是否齐全）。

【在整条流程中的位置】
    params/*.json  →  loader  →  ParamSet  →  parts_count / parts_stress  →  结果
                                     ↑
                              Web 层只负责告诉它"用哪个标准、哪个版本"

【为什么需要它】
需求里"参数可配置、可版本化管理、标注标准来源"这三条，本质上是同一件事：
计算引擎不写死任何数值，所有数值都从参数库来，并且每个数值都带着 source_ref。
这样换标准、换版本、换企业内规，只需要换 JSON，公式代码一行不改——报告也才能复现。

【术语】
  - λ_g / λ_b：基础失效率。可以理解为"一个典型器件在基准条件下的失效率水平"。
  - 因子族（family）：一类器件共享的因子公式形式。比如所有电解电容都用温度 5 次方律，
    只有指数不同的类别才需要单独覆盖。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ParamError(Exception):
    """参数库本身有问题（缺字段、引用不存在的因子族等）。"""


DEFAULT_PARAM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "params")


def _read_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise ParamError(f"参数库文件不存在：{path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class CategoryParam:
    """一个类别（如 CAP_ALU）在某标准下的完整计算规格。

    is_standard / note / pi_t_exempt 三个字段是为「标准没覆盖的零件」准备的：
    螺丝、支架、线缆这类非电子件在 MIL-217F 与 SR-332 里都没有失效率模型，
    但真实 BOM 里一定会有。把它们标成 is_standard=False 后，计算照常计入（保守方向），
    结果页与报告会单列出来提醒「这部分的数字不是标准值，不能拿去定稿」。
    如果直接静默跳过，MTBF 会凭空变好，那才是真正危险的做法。
    """

    code: str
    name: str
    group: str
    family: str
    lambda_g: float
    stress_spec: Dict[str, Any] = field(default_factory=dict)
    is_standard: bool = True           # False = 该标准未覆盖，λ 为工程假设值
    note: str = ""                     # 取值依据，展示在结果页与报告中
    pi_t_exempt: bool = False          # True = 不适用温度因子（机械件无结温概念）


@dataclass
class ParamSet:
    """一套标准参数。引擎只依赖这个对象，不依赖任何具体标准。"""

    standard: str
    version_tag: str
    display_name: str
    source_ref: str
    disclaimer: str
    engine_version: str
    environments: Dict[str, Dict[str, Any]]
    quality_levels: Dict[str, Dict[str, Any]]
    categories: Dict[str, CategoryParam]
    notes: Dict[str, str] = field(default_factory=dict)
    stress_lambda_factor: float = 0.8
    confidence_factor_90: float = 1.0

    # ---- 便捷查询 -------------------------------------------------------
    def env_label(self, code: str) -> str:
        return self.environments.get(code, {}).get("label", code)

    def env_mult(self, code: str) -> float:
        if code not in self.environments:
            raise ParamError(f"未知环境类别 {code}，可选：{list(self.environments)}")
        return float(self.environments[code]["mult"])

    def quality_label(self, code: str) -> str:
        return self.quality_levels.get(code, {}).get("label", code)

    def pi_q(self, code: str) -> float:
        if code not in self.quality_levels:
            raise ParamError(f"未知质量等级 {code}，可选：{list(self.quality_levels)}")
        return float(self.quality_levels[code]["pi_q"])

    def category(self, code: str) -> CategoryParam:
        if code not in self.categories:
            raise ParamError(f"参数库中没有类别 {code}")
        return self.categories[code]

    def has_category(self, code: str) -> bool:
        return code in self.categories

    def category_list(self) -> List[CategoryParam]:
        return list(self.categories.values())


def load_param_set(standard: str, param_dir: Optional[str] = None) -> ParamSet:
    """按标准名加载参数库。

    standard: "MIL-217F" 或 "TELCORDIA_SR332"
    """
    param_dir = param_dir or DEFAULT_PARAM_DIR
    filename = {
        "MIL-217F": "mil217f_v1.json",
        "TELCORDIA_SR332": "telcordia_sr332_v1.json",
    }.get(standard)
    if not filename:
        raise ParamError(f"不支持的标准：{standard}（可选 MIL-217F / TELCORDIA_SR332）")

    raw = _read_json(os.path.join(param_dir, filename))
    families = raw.get("families", {})
    categories: Dict[str, CategoryParam] = {}

    for code, spec in raw.get("categories", {}).items():
        family = spec.get("family", "")
        if family and family not in families:
            raise ParamError(f"类别 {code} 引用了不存在的因子族 {family}")

        # 合并：先取因子族模板，再用类别自己的覆盖项盖上去。
        # 这样"所有电容共用温度 5 次方律，但钽电容电压指数更严"这类差异只需要写一行。
        merged: Dict[str, Any] = {}
        if family:
            merged.update(families[family].get("parts_stress", {}))
        merged.update(spec.get("parts_stress", {}))

        if "lambda_g" not in spec:
            raise ParamError(f"类别 {code} 缺少 lambda_g（基础失效率）")

        categories[code] = CategoryParam(
            code=code,
            name=spec.get("name", code),
            group=spec.get("group", ""),
            family=family,
            lambda_g=float(spec["lambda_g"]),
            stress_spec=merged,
            is_standard=bool(spec.get("is_standard", True)),
            note=str(spec.get("note", "")),
            pi_t_exempt=bool(spec.get("pi_T_exempt", False)),
        )

    if not categories:
        raise ParamError("参数库中没有任何类别")

    return ParamSet(
        standard=raw["standard"],
        version_tag=raw["version_tag"],
        display_name=raw.get("display_name", raw["standard"]),
        source_ref=raw.get("source_ref", ""),
        disclaimer=raw.get("disclaimer", ""),
        engine_version=raw.get("engine_version", "1.0.0"),
        environments=raw["environments"],
        quality_levels=raw["quality_levels"],
        categories=categories,
        notes=raw.get("notes", {}),
        stress_lambda_factor=float(raw.get("stress_lambda_factor", 1.0)),
        confidence_factor_90=float(raw.get("confidence_factor_90", 1.0)),
    )


# ---------------------------------------------------------------------------
# 分类知识库 / 降额规则 / 磨损模型：其它三份参数文件
# ---------------------------------------------------------------------------


@dataclass
class CategoryDef:
    """分类知识库里的一个类目（含关键词、排除词、样例描述）。"""

    code: str
    parent: str
    name: str
    aliases: List[str]
    description: str
    keywords: List[Dict[str, Any]]
    negatives: List[str]
    samples: List[str]


def load_category_kb(param_dir: Optional[str] = None) -> Dict[str, Any]:
    """加载分类知识库。返回原始 dict + 类目对象列表，便于前端展示与引擎使用。"""
    param_dir = param_dir or DEFAULT_PARAM_DIR
    raw = _read_json(os.path.join(param_dir, "categories_v1.json"))
    cats = [
        CategoryDef(
            code=c["code"],
            parent=c.get("parent", ""),
            name=c["name"],
            aliases=c.get("aliases", []),
            description=c.get("description", ""),
            keywords=c.get("keywords", []),
            negatives=c.get("negatives", []),
            samples=c.get("samples", []),
        )
        for c in raw.get("categories", [])
    ]
    codes = {c.code for c in cats}
    for c in cats:
        if c.parent and c.parent not in {m["code"] for m in raw.get("major_categories", [])}:
            raise ParamError(f"类目 {c.code} 的父类目 {c.parent} 不存在")
    if len(codes) != len(cats):
        raise ParamError("分类知识库中存在重复的类目编码")

    return {
        "version_tag": raw.get("version_tag", "v1.0"),
        "major_categories": raw.get("major_categories", []),
        "categories": cats,
        "notes": raw.get("notes", {}),
    }


def load_derating_rules(param_dir: Optional[str] = None) -> Dict[str, Any]:
    param_dir = param_dir or DEFAULT_PARAM_DIR
    return _read_json(os.path.join(param_dir, "derating_v1.json"))


def load_wear_models(param_dir: Optional[str] = None) -> Dict[str, Any]:
    param_dir = param_dir or DEFAULT_PARAM_DIR
    return _read_json(os.path.join(param_dir, "wear_v1.json"))


def list_param_versions(param_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """给前端"参数库版本"页用的清单。"""
    param_dir = param_dir or DEFAULT_PARAM_DIR
    out = []
    for standard, fn in [
        ("MIL-217F", "mil217f_v1.json"),
        ("TELCORDIA_SR332", "telcordia_sr332_v1.json"),
        ("DERATING", "derating_v1.json"),
        ("WEAR", "wear_v1.json"),
        ("CATEGORY_KB", "categories_v1.json"),
    ]:
        path = os.path.join(param_dir, fn)
        if os.path.exists(path):
            raw = _read_json(path)
            out.append(
                {
                    "standard": standard,
                    "filename": fn,
                    "version_tag": raw.get("version_tag", ""),
                    "display_name": raw.get("display_name", ""),
                    "source_ref": raw.get("source_ref", ""),
                    "disclaimer": raw.get("disclaimer", ""),
                    "category_count": len(raw.get("categories", {})),
                }
            )
    return out
