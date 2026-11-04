"""
core/sens/sweep.py — 敏感性分析

【这个模块做什么】
把某个假设（环境温度 / 质量等级 / 通电占比）连续扫一遍，看 MTBF 怎么变，
并给出"哪个假设影响最大"的排序。

【在整条流程中的位置】
    已完成的评估 → sweep() → 曲线点集（前端画图）+ 弹性系数（报告结论）

【为什么需要它】
可靠性预计最大的问题不是算错，而是**假设错了没人知道**。同一份 BOM：
    环境温度 25°C → MTBF 假设 400 万小时
    环境温度 70°C → MTBF 假设 80 万小时
差 5 倍。如果报告只给一个数，读者会以为那是"客观事实"。
敏感性分析的作用是把这个不确定性摆到台面上：告诉你"这个结论有多依赖这条假设"。

【弹性系数（elasticity）怎么读】
    E = (ΔMTBF/MTBF) / (Δx/x)
    E = −2 表示"温度上升 10%，MTBF 下降 20%"。|E| 越大，说明结论对这个假设越敏感。
    温度是典型的强负相关（E 明显为负且绝对值大）；质量等级是阶跃式的（非线性）。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional

from ..models import Assumption, PartInput, SensitivityPoint, SensitivityResult
from ..reliability import parts_count, parts_stress
from ..standards.loader import ParamSet

VARIABLES = {
    "ambient_temp": {
        "label": "环境温度",
        "unit": "°C",
        "default_range": [25, 30, 35, 40, 45, 50, 55, 60, 65, 70],
    },
    "quality_level": {"label": "质量等级", "unit": "", "default_range": []},
    "duty_cycle": {
        "label": "日通电占比",
        "unit": "",
        "default_range": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    },
    "environment": {"label": "环境类别", "unit": "", "default_range": []},
}


def _run(parts: List[PartInput], assumption: Assumption, params: ParamSet) -> float:
    """跑一次评估，只取 MTBF。模式由 assumption.mode 决定。"""
    if assumption.mode == "parts_stress":
        res = parts_stress.assess(parts, assumption, params)
    else:
        res = parts_count.assess(parts, assumption, params)
    return res.mtbf_hours


def sweep(
    parts: List[PartInput],
    base: Assumption,
    params: ParamSet,
    variable: str = "ambient_temp",
    values: Optional[List[Any]] = None,
) -> SensitivityResult:
    """单变量扫描。"""
    if variable not in VARIABLES:
        raise ValueError(f"不支持的敏感性变量：{variable}")

    meta = VARIABLES[variable]
    labels: Dict[str, str] = {}

    if variable == "quality_level":
        values = values or list(params.quality_levels.keys())
        for q in values:
            labels[str(q)] = params.quality_label(str(q))
    elif variable == "environment":
        # 环境扫描：按环境严酷度排序，才有"曲线"的意义
        values = values or sorted(params.environments.keys(), key=lambda e: params.env_mult(e))
        for e in values:
            labels[str(e)] = params.env_label(str(e))
    else:
        values = values or meta["default_range"]

    points: List[SensitivityPoint] = []
    for v in values:
        if variable == "ambient_temp":
            a = replace(base, ambient_temp_c=float(v))
            label = f"{float(v):g}°C"
        elif variable == "duty_cycle":
            a = replace(base, duty_cycle=float(v))
            label = f"{float(v)*24:.1f} h/日"
        elif variable == "quality_level":
            a = replace(base, quality_level=str(v))
            label = labels.get(str(v), str(v))
        else:
            a = replace(base, environment=str(v))
            label = labels.get(str(v), str(v))

        mtbf = _run(parts, a, params)
        points.append(
            SensitivityPoint(
                x=float(v) if isinstance(v, (int, float)) else 0.0,
                label=label,
                mtbf_hours=mtbf,
                lambda_total_fit=(1e9 / mtbf) if mtbf > 0 else 0.0,
            )
        )

    finite = [p.mtbf_hours for p in points if p.mtbf_hours not in (float("inf"), 0)]
    elasticity = None
    if len(points) >= 2 and finite:
        p0, p1 = points[0], points[-1]
        if p0.mtbf_hours not in (0, float("inf")) and p1.mtbf_hours not in (0, float("inf")):
            dx = (p1.x - p0.x) / p0.x if p0.x else 0.0
            dmtbf = (p1.mtbf_hours - p0.mtbf_hours) / p0.mtbf_hours
            if dx:
                elasticity = round(dmtbf / dx, 3)

    swing = 0.0
    if finite:
        mn, mx = min(finite), max(finite)
        swing = round((mx - mn) / mn * 100, 1) if mn else 0.0

    return SensitivityResult(
        variable=variable,
        variable_label=meta["label"],
        x_unit=meta["unit"],
        points=points,
        elasticity=elasticity,
        total_swing_pct=swing,
        conclusion=_conclusion(variable, points, swing, elasticity),
    )


def _conclusion(variable, points, swing, elasticity) -> str:
    if len(points) < 2:
        return "扫描点不足，无法给结论。"
    low, high = points[0], points[-1]
    # 「曲线是平的」有两种原因：真的不敏感，或者当前口径里根本没有这一项。
    # 后者必须说清楚，否则用户会以为「温度不重要」——这是危险的误读。
    if swing < 0.5 and variable in ("ambient_temp", "duty_cycle"):
        return (
            f"{VARIABLES[variable]['label']} 从 {low.label} 变到 {high.label}，MTBF 几乎不变"
            f"（变化 {swing:.1f}%）。这不是「这一项不重要」，而是当前口径里没有它："
            "MIL-HDBK-217F 的零件计数法不含温度项，日通电占比也只影响 R(t) 的时间轴折算，"
            "都不进 λ。若要观察温度的真实影响，请改用零件应力法（含 π_T/π_V），"
            "或切换到 Telcordia SR-332（该方法自带 Arrhenius 温度项）。"
        )
    if variable == "ambient_temp":
        base = (
            f"温度从 {low.label} 升到 {high.label} 时，MTBF 由 {low.mtbf_hours:,.0f} h "
            f"变为 {high.mtbf_hours:,.0f} h，全区间变化 {swing:.0f}%。"
        )
        if elasticity is not None and elasticity < -0.5:
            base += "结论对温度高度敏感：散热设计比更换器件更能提升 MTBF。"
        else:
            base += "温度影响相对温和（常见于以 Arrhenius 模型为主的器件）。"
        return base
    if variable == "duty_cycle":
        return (
            f"日通电占比从 {low.label} 变到 {high.label} 时，MTBF 由 {low.mtbf_hours:,.0f} h "
            f"变为 {high.mtbf_hours:,.0f} h。注意 MTBF 本身不因 duty 变化（MIL 计数法下），"
            f"变化来自 Telcordia 的温度项/应力项；duty 主要通过折算 R(t) 的时间轴影响判定。"
            if abs(swing) < 1
            else f"日通电占比从 {low.label} 变到 {high.label}，MTBF 变化 {swing:.0f}%。"
        )
    if variable == "quality_level":
        return (
            f"质量等级从「{low.label}」改为「{high.label}」，MTBF 变化 {swing:.0f}%。"
            "这是阶跃式影响（查表因子），不是连续曲线——选型时按档次比较即可。"
        )
    return f"{VARIABLES[variable]['label']} 变化导致 MTBF 变化 {swing:.0f}%。"


def rank_assumptions(
    parts: List[PartInput], base: Assumption, params: ParamSet
) -> List[Dict[str, Any]]:
    """比较四个假设各自的影响幅度，用于报告里的一句话结论。

    做法：对每个假设施加一个"合理的变化量"，看 MTBF 变化百分比，然后排序。
    变化量的选择必须事先说明，否则读者无法理解"±10°C"是谁定的。
    """
    base_mtbf = _run(parts, base, params)
    rows: List[Dict[str, Any]] = []

    def add(name: str, change_desc: str, new_assumption: Assumption):
        m = _run(parts, new_assumption, params)
        delta = abs(m - base_mtbf) / base_mtbf * 100 if base_mtbf else 0.0
        rows.append(
            {
                "variable": name,
                "change": change_desc,
                "mtbf": m,
                "delta_pct": round(delta, 2),
            }
        )

    add("环境温度", "+10°C", replace(base, ambient_temp_c=base.ambient_temp_c + 10))
    qualities = list(params.quality_levels.keys())
    if base.quality_level in qualities:
        idx = qualities.index(base.quality_level)
        # 往"更差一档"的方向走（索引更大的通常更差，参数库里按商用→军品排列）
        worse = qualities[min(idx + 1, len(qualities) - 1)]
        if worse != base.quality_level:
            add("质量等级", f"{params.quality_label(base.quality_level)} → {params.quality_label(worse)}", replace(base, quality_level=worse))
    add("日通电占比", "8h/日 → 24h/日", replace(base, duty_cycle=1.0))

    envs = sorted(params.environments.keys(), key=lambda e: params.env_mult(e))
    cur = envs.index(base.environment) if base.environment in envs else 0
    if cur + 1 < len(envs):
        add("环境类别", f"{params.env_label(base.environment)} → {params.env_label(envs[cur+1])}", replace(base, environment=envs[cur + 1]))

    rows.sort(key=lambda r: r["delta_pct"], reverse=True)
    return rows
