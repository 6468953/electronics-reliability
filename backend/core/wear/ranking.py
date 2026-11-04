"""
core/wear/ranking.py — 磨损排行榜与"整机结论"合成

【这个模块做什么】
把两个视角的答案合起来，给出唯一一句能回答"这台设备实际能用多久"的结论：
    随机失效视角：由 MTBF 反推，达到目标存活率能撑多少年
    磨损视角    ：最短命的那个磨损件能撑多少年
    整机结论    ：两者取小（谁先到谁决定）

【在整条流程中的位置】
    AssessmentResult（随机失效）+ WearResult[]（磨损） → summarize() → 报告第 6 章 + 页面双轨图

【为什么要取 min，而不是平均或者只看 MTBF】
两个机制是"竞争关系"，不是"叠加关系"：产品失效是因为**最先发生的那一个**。
    并联/串联决定的是"结构上谁拖后腿"，
    min(随机, 磨损) 决定的是"机制上谁先到"。
这是可靠性工程里区分"随机失效"与"耗损失效"的标准做法（浴盆曲线：早期/随机/耗损三段）。
本系统覆盖后两段：随机段用指数分布，耗损段用确定性/威布尔模型。

【输出的措辞纪律】
不能说"产品能用 X 年"。正确表述是：
    "在假设条件下，主要限制机理是 <某零件的某机理>，预计 <N> 年后该机理导致失效；
     同时随机失效视角的 5 年存活率为 <R>%。"
因为磨损模型的输入（额定寿命、使用频次）本身就是假设，说成"能用 X 年"是过度承诺。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import AssessmentResult, Assumption, WearResult
from ..reliability import survival


def summarize(
    wear_results: List[WearResult],
    assessment: AssessmentResult,
    assumption: Assumption,
) -> Dict[str, Any]:
    """返回一个纯数据 dict，前端图表与 PDF 报告共用。"""
    t_random = survival.years_to_reach_survival(
        assessment.lambda_total_fit, assumption.target_survival, assumption.duty_cycle
    )

    if wear_results:
        limiting = min(wear_results, key=lambda r: r.life_years)
        t_wear = limiting.life_years
    else:
        limiting = None
        t_wear = float("inf")

    t_system = min(t_random, t_wear)
    if t_wear < t_random:
        limiting_mechanism = f"磨损：{limiting.part_number}（{limiting.mechanism_label}）"
        mechanism_kind = "wear"
    else:
        limiting_mechanism = "随机失效（MTBF 视角）"
        mechanism_kind = "random"

    # 结论句：把两边的数字都摆出来，让读者自己看到差距。
    if t_wear == float("inf") or t_random == float("inf"):
        conclusion = (
            "本次评估中至少一侧结果为无穷大（无失效率或未识别磨损件），"
            "请检查参数与分类是否完整后再解读结论。"
        )
    else:
        conclusion = (
            f"整机预计可用寿命约 {t_system:.1f} 年，由「{limiting_mechanism}」决定。"
            f"随机失效视角（{assumption.target_survival*100:.0f}% 存活率）可支撑 {t_random:.1f} 年，"
            f"磨损视角最短为 {t_wear:.1f} 年"
            + (
                f"（{limiting.part_number}）。两者相差 {t_random/t_wear:.1f} 倍，"
                "说明短板在耗损件而非随机失效——优先考虑换长寿命料或降低其工作温度。"
                if mechanism_kind == "wear" and t_random > t_wear * 1.5
                else "。"
            )
        )

    return {
        "limiting_mechanism": limiting_mechanism,
        "mechanism_kind": mechanism_kind,
        "t_random_years": None if t_random == float("inf") else round(t_random, 2),
        "t_wear_years": None if t_wear == float("inf") else round(t_wear, 2),
        "t_system_years": None if t_system == float("inf") else round(t_system, 2),
        "target_years": assumption.target_years,
        "wear_count": len(wear_results),
        "limiting_part_id": limiting.part_id if limiting else None,
        "conclusion": conclusion,
        "items": [
            {
                "part_id": r.part_id,
                "part_number": r.part_number,
                "description": r.description,
                "category_code": r.category_code,
                "mechanism": r.mechanism,
                "mechanism_label": r.mechanism_label,
                "life_hours": None if r.life_hours == float("inf") else round(r.life_hours, 0),
                "life_years": None if r.life_years == float("inf") else round(r.life_years, 2),
                "formula": r.formula,
                "inputs": r.inputs,
                "using_defaults": r.using_defaults,
                "note": r.note,
                "is_limiting": r.is_limiting,
            }
            for r in wear_results
        ],
    }
