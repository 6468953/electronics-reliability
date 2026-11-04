"""
core/derating/checker.py — 降额检查（Derating Check）

【这个模块做什么】
逐零件比较"实际工作应力"与"额定值"，按规范上限给出三级判定：满足 / 接近 / 超限。

【在整条流程中的位置】
    BOM（额定值，解析或手填） + 工作应力  →  checker  →  违规清单  →  报告第 7 章

【为什么降额比失效率更"日常"】
失效率算出来是一个抽象数字，工程师很难据此改设计。降额检查不一样：
它直接告诉你"这只电容的电压用到了额定的 92%，规范要求不超过 80%，请换 35V 的"。
这是能在半小时内改完的动作，所以降额是工程上落地性最强的一环。

【判定逻辑（三级 + 缺数据）】
    ratio = 工作应力 / 额定值
    ratio ≤ warn_ratio              → pass（满足）      绿
    warn_ratio < ratio ≤ max_ratio  → marginal（接近）  黄
    ratio > max_ratio               → violation（超限） 红
    ratio > 1.0                     → 额外标注"超额定"（可能随时失效）
    缺额定值或工作应力              → no_data（缺数据）灰，可人工补录

    warn_ratio 默认 = max_ratio − 0.1（参数库 default_warn_margin）。
    这个 10% 缓冲带是【本系统的约定】，不是标准规定：它表达"虽然没违规，但余量已经很薄"。
    之所以要这一档，是因为工程上出问题的往往不是"明确违规"的件，而是"刚好卡线"的件。

【温度类规则的特别处理】
温度不能按比例降额——把 105℃ 的电容按 80% 算成 84℃，在物理上没有意义。
所以温度类规则用"绝对余量"表达：工作温度应至少低于额定上限 margin_c（默认 10°C）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import Assumption, DeratingResult, PartInput
from ..parse_spec import merge_rated

# 比值判定的浮点容差。见下方 ratio 比较处的说明。
EPS = 1e-9


def _num(d: Dict[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        v = (d or {}).get(k)
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def check_part(
    part: PartInput, assumption: Assumption, rules_cfg: Dict[str, Any]
) -> List[DeratingResult]:
    """对一个零件套用它所属类别的所有降额规则。"""
    rules = (rules_cfg.get("rules") or {}).get(part.category_code, [])
    if not rules:
        return []

    default_margin = float(rules_cfg.get("default_warn_margin", 0.1))
    rated, rated_src = merge_rated(part.rated, part.description)
    stress = part.stress or {}
    out: List[DeratingResult] = []

    for rule in rules:
        stress_type = rule.get("stress_type", "")
        rule_type = rule.get("rule_type", "ratio")
        max_ratio = float(rule.get("max_ratio", 1.0))
        warn_ratio = float(rule.get("warn_ratio", max(0.0, max_ratio - default_margin)))
        note = rule.get("note", "")
        source = rules_cfg.get("source_ref", "")

        if rule_type == "margin":
            # 温度类：用绝对余量判定
            t_rated = _num(rated, rule.get("rated_field", "temp_max_c"))
            margin_c = float(rule.get("margin_c", 10))
            rise = _num(stress, "temp_rise_c", "delta_t_c")
            if rise is None:
                rise = 0.0
            t_op = assumption.ambient_temp_c + rise

            if t_rated is None:
                out.append(
                    DeratingResult(
                        part_id=part.part_id, part_number=part.part_number,
                        category_code=part.category_code,
                        category_name=part.category_code,
                        stress_type=stress_type, rated_value=None, applied_value=t_op,
                        ratio=None, max_ratio=max_ratio, warn_ratio=warn_ratio,
                        verdict="no_data", rule_source=source,
                        note="描述中未解析到额定最高温度，请人工补录 temp_max_c。",
                    )
                )
                continue

            allowed = t_rated - margin_c
            if t_op <= allowed:
                verdict = "pass"
            elif t_op <= t_rated:
                verdict = "marginal"
            else:
                verdict = "violation"

            ratio = t_op / t_rated if t_rated else None
            extra = ""
            if t_op > t_rated:
                extra = f"；工作温度 {t_op:.0f}°C 已超过额定上限 {t_rated:.0f}°C"
            out.append(
                DeratingResult(
                    part_id=part.part_id, part_number=part.part_number,
                    category_code=part.category_code, category_name=part.category_code,
                    stress_type=stress_type, rated_value=t_rated, applied_value=round(t_op, 1),
                    ratio=round(ratio, 4) if ratio else None,
                    max_ratio=max_ratio, warn_ratio=warn_ratio, verdict=verdict,
                    rule_source=source,
                    note=f"要求 T_op ≤ T_max − {margin_c:g}°C = {allowed:.0f}°C{extra}。{note}",
                )
            )
            continue

        # 比例类：电压 / 电流 / 功率
        rated_v = _num(rated, rule.get("rated_field", stress_type))
        applied_v = _num(stress, rule.get("applied_field", stress_type))
        applied_src = "用户填写" if applied_v is not None else "缺失"

        if rated_v is None or applied_v is None:
            missing = []
            if rated_v is None:
                missing.append(f"额定{_cn(stress_type)}")
            if applied_v is None:
                missing.append(f"工作{_cn(stress_type)}")
            out.append(
                DeratingResult(
                    part_id=part.part_id, part_number=part.part_number,
                    category_code=part.category_code, category_name=part.category_code,
                    stress_type=stress_type, rated_value=rated_v, applied_value=applied_v,
                    ratio=None, max_ratio=max_ratio, warn_ratio=warn_ratio,
                    verdict="no_data", rule_source=source,
                    note=f"缺 {' 与 '.join(missing)}，无法判定。可在下方补录后重算。",
                )
            )
            continue

        ratio = applied_v / rated_v if rated_v else None
        if ratio is None:
            verdict = "no_data"
        # 浮点比较必须带容差：2.1 / 3.0 = 0.7000000000000001，直接和上限 0.7 比会判成
        # "超限"，而实际含义是"正好卡在上限上"。这类差一位的误判会被用户当成系统错误。
        elif ratio <= warn_ratio + EPS:
            verdict = "pass"
        elif ratio <= max_ratio + EPS:
            verdict = "marginal"
        else:
            verdict = "violation"

        extra = ""
        if ratio > 1.0:
            extra = "；比值 > 1，工作应力已超过额定值，随时可能失效"
        out.append(
            DeratingResult(
                part_id=part.part_id, part_number=part.part_number,
                category_code=part.category_code, category_name=part.category_code,
                stress_type=stress_type, rated_value=rated_v, applied_value=applied_v,
                ratio=round(ratio, 4), max_ratio=max_ratio, warn_ratio=warn_ratio,
                verdict=verdict, rule_source=source,
                note=(
                    f"规范要求 {_cn(stress_type)} ≤ 额定 × {max_ratio:.0%}"
                    f"（当前 {ratio:.1%}，来源：{applied_src} + "
                    f"{'描述解析' if rated_src.get(rule.get('rated_field', stress_type)) == 'parsed' else '人工录入'}）"
                    f"{extra}。{note}"
                ),
            )
        )

    return out


def _cn(stress_type: str) -> str:
    return {
        "voltage": "电压",
        "current": "电流",
        "power": "功率",
        "temperature": "温度",
    }.get(stress_type, stress_type)


def check_all(
    parts: List[PartInput], assumption: Assumption, rules_cfg: Dict[str, Any]
) -> List[DeratingResult]:
    results: List[DeratingResult] = []
    for p in parts:
        results.extend(check_part(p, assumption, rules_cfg))
    order = {"violation": 0, "marginal": 1, "no_data": 2, "pass": 3}
    results.sort(key=lambda r: (order.get(r.verdict, 9), -(r.ratio or 0)))
    return results


def summarize(results: List[DeratingResult]) -> Dict[str, Any]:
    counts = {"pass": 0, "marginal": 0, "violation": 0, "no_data": 0}
    for r in results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    total = len(results)
    return {
        "total": total,
        **counts,
        "violation_pct": round(counts["violation"] / total * 100, 1) if total else 0.0,
        "conclusion": (
            f"共检查 {total} 项应力约束：{counts['violation']} 项超限、{counts['marginal']} 项接近上限、"
            f"{counts['no_data']} 项缺数据。"
            + ("存在超限项，建议在改版前优先处理。" if counts["violation"] else "无超限项。")
        ),
    }
