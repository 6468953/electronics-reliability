"""
core/reliability/aggregate.py — 结果汇总、判定与预警

【这个模块做什么】
两种计算模式（零件计数法 / 零件应力法）最后都要做同样几件事：把整机 λ 转成 MTBF 与 R(t)、
和指标比对给出 PASS/FAIL、按贡献排序找短板、把可疑之处整理成预警清单。这些逻辑只写一次。

【在整条流程中的位置】
    parts_count / parts_stress  →  finalize()  →  AssessmentResult（报告与页面直接消费）

【为什么需要它】
判定规则如果散落在两个计算文件里，很容易出现"两种模式给出不同口径结论"的尴尬。
集中在一处，也方便以后加新的判定口径（比如同时看 MTBF 门槛与存活率门槛）。

【判定逻辑（写清楚，避免用户误解）】
    PASS 需同时满足：
      1) R(t_目标) ≥ 目标存活率。这是主判据，直接回答"5 年后还有多少台是好的"。
      2) 若填了 MTBF 门槛，则 MTBF ≥ 门槛值。这是行业常见的采购指标口径
         （如"MTBF ≥ 43 万小时""≥ 100 万小时"）。
    只有 1) 时，判定只看存活率；"MTBF 门槛"是可选的第二道闸。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..models import AssessmentResult, Assumption, PartResult
from . import survival
from .rbd import RbdModel

DISCLAIMER = (
    "可靠性预计反映的是随机失效，精度为数量级参考（通常 ±2~5 倍），"
    "不代表实测寿命与现场故障率；实际验证需通过 RDT（可靠性增长试验/可靠性验证试验）"
    "或现场数据积累。本系统参数为示例值，仅用于演示与学习。"
)


def compute_top_contributors(
    parts: List[PartResult], rbd_model: RbdModel, top_n: int = 10
) -> List[Dict[str, object]]:
    """按失效率贡献排序，返回 Top N（含累计占比）。

    并联组里的成员：把组的等效 λ 按成员原 λ 的比例分摊，这样排序仍然反映
    "谁贡献大"，但总和不会超过整机 λ（否则占比加总会大于 100%，图就错了）。
    """
    group_adjust: Dict[int, float] = {}
    for g in rbd_model.groups:
        if g.member_lambda_sum <= 0:
            continue
        ratio = g.lambda_equiv / g.member_lambda_sum
        for pid in g.member_ids:
            group_adjust[pid] = ratio

    rows = []
    total = sum(p.lambda_part for p in parts) or 1.0
    for p in parts:
        eff = p.lambda_part * group_adjust.get(p.part_id, 1.0)
        rows.append(
            {
                "part_id": p.part_id,
                "part_number": p.part_number,
                "category_code": p.category_code,
                "category_name": p.category_name,
                "qty": p.qty,
                "lambda_part": round(eff, 6),
                "contribution_pct": round(eff / total * 100.0, 3),
                "in_redundancy_group": p.part_id in group_adjust,
            }
        )

    rows.sort(key=lambda r: r["lambda_part"], reverse=True)
    cumulative = 0.0
    for r in rows:
        cumulative += r["contribution_pct"]
        r["cumulative_pct"] = round(cumulative, 3)
    return rows[:top_n]


def build_warnings(
    parts: List[PartResult],
    rbd_model: RbdModel,
    r_at_target: float,
    assumption: Assumption,
) -> List[str]:
    """把"结果可能不可信"的地方全部翻出来。宁可得罪人，也不要让用户拿着错的数去决策。"""
    warns: List[str] = []

    default_count = sum(1 for p in parts if any(step.is_default for step in p.trace))
    if default_count:
        warns.append(
            f"{default_count} 个零件使用了默认应力/温升数据（追溯中标为「默认」），"
            "这些零件的失效率属于量级估算，结果整体偏乐观。建议补录工作电压、功率或温升。"
        )

    single_member_groups = [
        g for g in rbd_model.groups if len(g.member_ids) < 2
    ]
    if single_member_groups:
        warns.append("存在只有 1 个成员的冗余组，已按串联处理（单件冗余没有收益）。")

    if rbd_model.groups:
        warns.append(
            "并联冗余的收益按「共因失效可忽略」计算，是收益上限。"
            "若冗余件共用电源、共用散热或同批次同供应商，实际收益会显著低于此值。"
        )

    if r_at_target < assumption.target_survival:
        warns.append(
            f"目标年限存活率 {r_at_target*100:.2f}% 低于要求的 {assumption.target_survival*100:.1f}%，"
            "判定为不通过。优先看下方短板 Top 列表决定换料方向。"
        )

    if parts:
        top = max(parts, key=lambda p: p.lambda_part)
        total = sum(p.lambda_part for p in parts) or 1.0
        if top.lambda_part / total > 0.5 and len(parts) > 3:
            warns.append(
                f"单件贡献超过整机失效率的一半（{top.part_number}，"
                f"{top.lambda_part/total*100:.1f}%）。这类「一家独大」通常意味着参数或用量有异常，"
                "建议先核对用量与工作条件，再谈换料。"
            )

    if survival.mtbf_from_fit(rbd_model.lambda_total) > 5e9:
        warns.append(
            "整机 MTBF 超过 50 亿小时，明显高于实际工程经验，通常是假设过于乐观"
            "（例如按单板少量零件计算、未计入焊点/连接器/线缆）。请核对评估范围。"
        )

    if assumption.ambient_temp_c > 70:
        warns.append(
            f"环境温度 {assumption.ambient_temp_c:g}°C 偏高，多个器件已接近或超过商用级上限（70°C），"
            "预计结果对温度假设极其敏感，请看敏感性分析。"
        )

    return warns


def build_survival_curve(lambda_fit: float, years: List[float], duty_cycle: float) -> List[Dict[str, float]]:
    """给前端 R(t) 曲线用：[{year, r}]。"""
    return [
        {
            "year": float(y),
            "r": round(survival.survival_at_years(lambda_fit, y, duty_cycle), 6),
        }
        for y in years
    ]


def finalize(
    *,
    parts: List[PartResult],
    rbd_model: RbdModel,
    assumption: Assumption,
    param_version: str,
    engine_version: str,
    disclaimers: Optional[List[str]] = None,
) -> AssessmentResult:
    """把零件结果收束成一份完整评估结论。"""
    lambda_total = rbd_model.lambda_total
    mtbf = survival.mtbf_from_fit(lambda_total)
    t_op = survival.operating_hours(assumption.target_years, assumption.duty_cycle)
    r_at_target = survival.survival(lambda_total, t_op)

    reasons: List[str] = []
    verdict = "PASS"
    if r_at_target < assumption.target_survival:
        verdict = "FAIL"
        reasons.append(
            f"存活率不达标：{assumption.target_years:g} 年（{t_op:,.0f} 通电小时）存活率 "
            f"{r_at_target*100:.2f}% < 目标 {assumption.target_survival*100:.1f}%"
        )
    else:
        reasons.append(
            f"存活率达标：{assumption.target_years:g} 年（{t_op:,.0f} 通电小时）存活率 "
            f"{r_at_target*100:.2f}% ≥ 目标 {assumption.target_survival*100:.1f}%"
        )

    if assumption.mtbf_threshold_hours:
        if mtbf < assumption.mtbf_threshold_hours:
            verdict = "FAIL"
            reasons.append(
                f"MTBF 未达门槛：{mtbf:,.0f} h < 门槛 {assumption.mtbf_threshold_hours:,.0f} h"
            )
        else:
            reasons.append(
                f"MTBF 达门槛：{mtbf:,.0f} h ≥ 门槛 {assumption.mtbf_threshold_hours:,.0f} h"
            )

    warnings = build_warnings(parts, rbd_model, r_at_target, assumption)

    return AssessmentResult(
        standard=assumption.standard,
        mode=assumption.mode,
        param_version=param_version,
        engine_version=engine_version,
        lambda_total_fit=round(lambda_total, 6),
        mtbf_hours=mtbf,
        r_at_target=r_at_target,
        operating_hours=t_op,
        verdict=verdict,
        verdict_reasons=reasons,
        parts=parts,
        redundancy=rbd_model.groups,
        top_contributors=compute_top_contributors(parts, rbd_model),
        warnings=warnings + (disclaimers or []),
        disclaimer=DISCLAIMER,
    )
