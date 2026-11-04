"""
core/wear/models.py — 磨损机理寿命估算

【这个模块做什么】
按机理分别估算"磨损件"能用多久：电解电容干涸、风扇轴承、继电器触点、LED 光衰、
连接器插拔。这是对 MTBF 的补盲——**MTBF 说"多久坏一次"，磨损说"能用多久"**。

【在整条流程中的位置】
    BOM（含额定寿命/温度/次数） + 环境温度 + duty  →  本模块  →  磨损排行榜 → 整机结论
                                                                    ↑
                                                    与 MTBF 视角取 min（ranking.py）

【为什么必须单独算】
举个真实感很强的例子：一台电源，MTBF 算出来 100 万小时（约 114 年），
但里面有一只 105℃/2000h 的电解电容工作在 65℃：
    L = 2000 × 2^((105−65)/10) = 2000 × 16 = 32000 小时 ≈ 3.7 年（24h 连续运行）
也就是说，"随机失效视角 114 年"和"磨损视角 3.7 年"差了 30 倍。
只报 MTBF 会得出荒谬结论——这正是行业里"MTBF 高不等于寿命长"的由来。

【三个模型的物理含义】
1) 10°C 法则（double_every_10c）
   化学反应速率随温度按 Arrhenius 上升，在 Ea≈0.6eV 附近，"每升 10°C 速率翻倍"。
   电解电容的电解液干涸正是这种化学反应，所以厂商手册普遍用 L = L0 × 2^((Tmax−Top)/10)。
   注意方向：**温度越低寿命越长**，所以降额与散热是延长寿命最有效的手段。

2) Arrhenius（arrhenius）
   显式使用活化能：L = L_ref × exp((Ea/k)(1/T_op − 1/T_ref))。
   LED 光衰用这个，因为不同芯片/荧光粉体系的 Ea 差异大，需要可配置。

3) 次数计数（cycle_count）
   机械动作类：寿命 = 额定次数 / (每天动作次数 × 365)。
   继电器、开关、连接器属于这类——它们不是"随时间坏"，而是"随动作次数坏"。

【缺数据怎么办】
一律走"保守默认值"并在结果里标出来：宁可报低让人去查 datasheet，
也不要报高让人以为安全。每条默认值都记录在 using_defaults 里，报告会单独列出。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import Assumption, PartInput, WearResult
from ..parse_spec import merge_rated

K_BOLTZMANN_EV = 8.617333262e-5
HOURS_PER_YEAR = 8760.0

# 器件自升温的保守默认值（°C）。取偏大的值，让寿命估算偏悲观。
# 为什么偏悲观：自升温每高 10°C 电解电容寿命就减半，估低了会让人以为"还能用很久"。
WEAR_DELTA_DEFAULT = {
    "electrolytic_dryout": 5.0,
    "module_cap_dryout": 5.0,
    "fan_bearing_L10": 5.0,
    "led_lumen": 10.0,
    "film_self_healing": 3.0,
    "relay_contact": 0.0,
    "switch_contact": 0.0,
    "connector_mate": 0.0,
}


def _pick(d: Dict[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        v = d.get(k)
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _operating_temp(part: PartInput, assumption: Assumption, mechanism: str) -> tuple:
    """器件工作温度 = 环境温度 + 自升温。返回 (T_op, 是否用了默认温升)。"""
    rise = _pick(part.stress or {}, "temp_rise_c", "delta_t_c")
    if rise is not None:
        return assumption.ambient_temp_c + rise, False
    return assumption.ambient_temp_c + WEAR_DELTA_DEFAULT.get(mechanism, 0.0), True


def _voltage_factor(v_applied: Optional[float], v_rated: Optional[float], params: Dict[str, Any]) -> tuple:
    """电解电容的电压修正系数 K_V。

    依据：工作电压越接近额定，内部场强与漏电流越大，干涸越快。
    这不是标准公式，是工程近似（已在参数库 note 中声明）：
        比值 ≤ ref(0.8) → 1.0
        超出后每超出 1.0（100%）打折 penalty(3.5)，下限 floor(0.3)
    """
    ref = float(params.get("voltage_derate_ref", 0.8))
    penalty = float(params.get("voltage_penalty_per_unit", 3.5))
    floor = float(params.get("voltage_floor", 0.3))
    if not v_applied or not v_rated:
        return 1.0, True
    ratio = v_applied / v_rated
    if ratio <= ref:
        return 1.0, False
    return max(floor, 1.0 - (ratio - ref) * penalty), False


def _eval_double_every_10c(
    part: PartInput, assumption: Assumption, mech_cfg: Dict[str, Any], defaults: List[str]
) -> Dict[str, Any]:
    p = mech_cfg.get("params", {})
    rated, _src = merge_rated(part.rated, part.description)
    t_op, rise_default = _operating_temp(part, assumption, mech_cfg["mechanism"])
    if rise_default:
        defaults.append("器件自升温（按类别默认值估算）")

    l0 = _pick(rated, "life_h")
    if l0 is None:
        l0 = float(p.get("L0_default_h", 2000))
        defaults.append(f"额定寿命 L0（默认 {l0:g} h）")

    t_max = _pick(rated, "temp_max_c")
    if t_max is None:
        t_max = float(p.get("temp_max_default_c", 105))
        defaults.append(f"额定最高温度 T_max（默认 {t_max:g}°C）")

    kv, kv_default = _voltage_factor(
        _pick(part.stress or {}, "voltage"), _pick(rated, "voltage"), p
    )
    if kv_default:
        defaults.append("电压修正系数 K_V（缺电压数据，取 1.0 偏乐观）")

    life = l0 * (2.0 ** ((t_max - t_op) / 10.0)) * kv
    formula = (
        f"L = L0 × 2^((T_max − T_op)/10) × K_V = {l0:g} × 2^(({t_max:g} − {t_op:g})/10) × {kv:.3f}"
        f" = {life:,.0f} h"
    )
    return {
        "life_hours": life,
        "formula": formula,
        "inputs": {
            "L0_h": l0,
            "T_max_c": t_max,
            "T_op_c": round(t_op, 2),
            "delta_t_c": round(t_op - assumption.ambient_temp_c, 2),
            "K_V": round(kv, 4),
            "ambient_c": assumption.ambient_temp_c,
        },
    }


def _eval_arrhenius(
    part: PartInput, assumption: Assumption, mech_cfg: Dict[str, Any], defaults: List[str]
) -> Dict[str, Any]:
    p = mech_cfg.get("params", {})
    rated, _src = merge_rated(part.rated, part.description)
    t_op, rise_default = _operating_temp(part, assumption, mech_cfg["mechanism"])
    if rise_default:
        defaults.append("器件自升温（按类别默认值估算）")

    ref_life = _pick(rated, "life_h", "l70_h")
    if ref_life is None:
        ref_life = float(p.get("L70_ref_h", 25000))
        defaults.append(f"参考寿命 L70_ref（默认 {ref_life:g} h）")

    t_ref = _pick(rated, "ref_temp_c")
    if t_ref is None:
        t_ref = float(p.get("temp_ref_c", 85))
        defaults.append(f"参考温度 T_ref（默认 {t_ref:g}°C）")

    ea = float(p.get("ea_ev", 0.5))
    exponent = (ea / K_BOLTZMANN_EV) * (1.0 / (t_op + 273.15) - 1.0 / (t_ref + 273.15))
    life = ref_life * pow(2.718281828459045, exponent)
    formula = (
        f"L = L_ref × exp((Ea/k)(1/T_op − 1/T_ref)) = {ref_life:g} × exp({exponent:.4f})"
        f" = {life:,.0f} h（Ea={ea}eV, T_ref={t_ref:g}°C, T_op={t_op:g}°C）"
    )
    return {
        "life_hours": life,
        "formula": formula,
        "inputs": {
            "L_ref_h": ref_life,
            "Ea_eV": ea,
            "T_ref_c": t_ref,
            "T_op_c": round(t_op, 2),
            "exponent": round(exponent, 6),
        },
    }


def _eval_cycle_count(
    part: PartInput, assumption: Assumption, mech_cfg: Dict[str, Any], defaults: List[str]
) -> Dict[str, Any]:
    p = mech_cfg.get("params", {})
    rated, _src = merge_rated(part.rated, part.description)

    cycles = _pick(rated, "cycles", "rated_cycles")
    if cycles is None:
        cycles = float(p.get("rated_cycles_default", 100000))
        defaults.append(f"额定动作次数（默认 {cycles:,.0f} 次）")

    daily = _pick(part.stress or {}, "daily_ops", "ops_per_day")
    if daily is None:
        daily = float(p.get("daily_ops_default", 10))
        defaults.append(f"日动作次数（默认 {daily:g} 次/日）")

    if daily <= 0:
        daily = 0.01  # 防止除零：约每月动作 0.3 次
        defaults.append("日动作次数为 0，按 0.01 次/日 处理")

    years = cycles / (daily * 365.0)
    life_hours = years * HOURS_PER_YEAR * max(1e-6, assumption.duty_cycle)
    formula = (
        f"年限 = 额定次数 / (日次数 × 365) = {cycles:,.0f} / ({daily:g} × 365) = {years:,.1f} 年"
        f"（按日通电 {assumption.duty_cycle*24:.1f}h 折算 {life_hours:,.0f} 通电小时）"
    )
    return {
        "life_hours": life_hours,
        "life_years_override": years,
        "formula": formula,
        "inputs": {"rated_cycles": cycles, "daily_ops": daily},
    }


EVALUATORS = {
    "double_every_10c": _eval_double_every_10c,
    "arrhenius": _eval_arrhenius,
    "cycle_count": _eval_cycle_count,
}


def assess_wear(
    parts: List[PartInput], assumption: Assumption, wear_cfg: Dict[str, Any]
) -> List[WearResult]:
    """对 BOM 中所有"有磨损模型"的零件逐个估算寿命。"""
    models = wear_cfg.get("models", {})
    results: List[WearResult] = []
    duty = max(1e-6, min(1.0, assumption.duty_cycle))

    for part in parts:
        cfg = models.get(part.category_code)
        if not cfg:
            continue

        evaluator = EVALUATORS.get(cfg.get("model", ""))
        if evaluator is None:
            continue

        defaults: List[str] = []
        try:
            out = evaluator(part, assumption, cfg, defaults)
        except Exception as exc:  # 单个零件算不出来，不该让整份评估崩掉
            results.append(
                WearResult(
                    part_id=part.part_id,
                    part_number=part.part_number,
                    description=part.description,
                    category_code=part.category_code,
                    mechanism=cfg.get("mechanism", ""),
                    mechanism_label=cfg.get("label", ""),
                    life_hours=float("inf"),
                    life_years=float("inf"),
                    formula="计算失败",
                    inputs={},
                    using_defaults=[],
                    note=f"该零件寿命无法估算：{exc}",
                )
            )
            continue

        life_hours = float(out["life_hours"])
        life_years = float(out.get("life_years_override") or life_hours / (HOURS_PER_YEAR * duty))

        results.append(
            WearResult(
                part_id=part.part_id,
                part_number=part.part_number,
                description=part.description,
                category_code=part.category_code,
                mechanism=cfg.get("mechanism", ""),
                mechanism_label=cfg.get("label", ""),
                life_hours=life_hours,
                life_years=life_years,
                formula=out["formula"],
                inputs=out["inputs"],
                using_defaults=defaults,
                note=cfg.get("note", ""),
            )
        )

    results.sort(key=lambda r: r.life_years)
    if results:
        results[0].is_limiting = True
    return results
