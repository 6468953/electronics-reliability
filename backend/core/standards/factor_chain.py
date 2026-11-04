"""
core/standards/factor_chain.py — 因子链求值引擎

【这个模块做什么】
可靠性预计的公式本质上都是同一个形状：

    λ_零件 = λ_b × π_T × π_V × π_S × π_Q × π_E   （参与哪几项，各类别不同）

本模块把这串乘法做成一件事：**按参数库声明的公式形式，逐项求出每个 π 因子的数值，
并留下完整的追溯记录**（用了什么公式、代入了什么、结果是多少、依据哪一条标准）。

【在整条流程中的位置】
    CategoryParam.stress_spec ─┐
    Assumption（环境/温度/质量）├→ evaluate_chain() → [π_T, π_V, π_S, π_Q, π_E] → 乘起来
    PartInput.stress / rated  ─┘

【为什么需要它】
如果每个类别都写一段 if/else 硬算，那么"钽电容电压指数比电解电容更严"这类行业共识
就只能靠改代码实现，而改代码 = 改报告口径 = 无法复现。做成声明式之后，
公式形式写在 JSON 里，代码只负责"照着算"，领域工程师可以自己核对参数文件。

【术语速查】
  π_T 温度因子 ：温度越高失效率越高。两种常见形式——
        · 幂律（power_law）：π_T = ((T+273)/(T_ref+273))^n，MIL-217 电容/电阻类用这类形式；
        · Arrhenius：π_T = exp((Ea/k)(1/T_ref − 1/T_op))，化学反应速率对温度的经典描述，
          Ea 是"活化能"（eV），k 是玻尔兹曼常数。
  π_V 电压应力因子：工作电压越接近额定电压，失效率越高。
  π_S 功率/电应力因子：同理，按功率（或电流）占比修正。
  π_Q 质量因子  ：器件质量等级。商用级 > 工业级 > 车规级 > 军品级（数值越大越差）。
  π_E 环境因子  ：使用环境严酷度。地面固定 GB = 1 为基准，机载/航天可达 10~20 倍。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 玻尔兹曼常数（eV/K）。Arrhenius 公式里把"活化能/温度"换算成无量纲指数的桥梁。
K_BOLTZMANN_EV = 8.617333262e-5

# 绝对零度偏移：°C → K 必须加 273.15，这是最常见的新手错误点（直接用 °C 代入会让 π_T 差几倍）。
KELVIN_OFFSET = 273.15


@dataclass
class FactorEval:
    """一个 π 因子的求值结果（同时也是追溯里的一步）。"""

    key: str
    name: str
    value: float
    formula: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    is_default: bool = False
    note: str = ""

    def as_trace_dict(self, step_no: int) -> Dict[str, Any]:
        return {
            "step": step_no,
            "name": self.name,
            "formula": self.formula,
            "inputs": self.inputs,
            "value": round(self.value, 6),
            "unit": "-",
            "source": self.source,
            "is_default": self.is_default,
            "note": self.note,
        }


FACTOR_LABELS: Dict[str, tuple] = {
    "pi_T": ("温度因子 π_T", "温度对失效率的放大倍数。以基准温度为 1.0，温度越高，化学反应（迁移、氧化）越快。"),
    "pi_V": ("电压应力因子 π_V", "工作电压相对额定电压的放大倍数。电压越接近额定值，介质击穿风险越高。"),
    "pi_S": ("功率应力因子 π_S", "工作功率（或电流）相对额定的放大倍数。发热与电迁移是主因。"),
    "pi_Q": ("质量因子 π_Q", "器件质量等级的放大倍数。军品级 < 车规级 < 工业级 < 商用级（数值越小越好）。"),
    "pi_E": ("环境因子 π_E", "使用环境严酷度的放大倍数。以地面固定机房为 1.0，车载/机载/航天依次升高。"),
}


def _k(temp_c: float) -> float:
    return temp_c + KELVIN_OFFSET


def eval_power_law(spec: Dict[str, Any], t_op_c: float) -> tuple:
    """π_T = ((T_op + 273.15) / (T_ref + 273.15)) ^ n"""
    ref = float(spec.get("ref_temp_c", 25.0))
    n = float(spec.get("exponent", 3.0))
    value = (_k(t_op_c) / _k(ref)) ** n
    formula = f"π_T = ((T_op+273.15)/(T_ref+273.15))^{n} = (({t_op_c:.1f}+273.15)/({ref:.1f}+273.15))^{n}"
    return value, formula, {"T_op_c": round(t_op_c, 2), "T_ref_c": ref, "exponent": n, "model": "power_law"}


def eval_arrhenius(spec: Dict[str, Any], t_op_c: float) -> tuple:
    """π_T = exp( (Ea/k) × (1/T_ref − 1/T_op) )，温度必须用开尔文。"""
    ea = float(spec.get("ea_ev", 0.35))
    ref = float(spec.get("ref_temp_c", 40.0))
    exponent = (ea / K_BOLTZMANN_EV) * (1.0 / _k(ref) - 1.0 / _k(t_op_c))
    value = pow(2.718281828459045, exponent)
    formula = (
        f"π_T = exp((Ea/k)(1/T_ref − 1/T_op))，Ea={ea}eV, T_ref={ref}°C, T_op={t_op_c:.1f}°C"
        f" → π_T = exp({exponent:.4f})"
    )
    return value, formula, {
        "Ea_eV": ea,
        "T_ref_K": round(_k(ref), 2),
        "T_op_K": round(_k(t_op_c), 2),
        "exponent": round(exponent, 6),
        "model": "arrhenius",
    }


def eval_power_plus_one(spec: Dict[str, Any], applied: float, rated: float) -> tuple:
    """π_V / π_S = (工作应力 / 额定应力)^m + 1

    这是 MIL-217 系列应力因子的常见形式：当工作应力 = 额定应力时，因子约等于 2；
    应力越大增长越快（指数 m 按器件类型不同）。
    """
    m = float(spec.get("exponent", 1.0))
    ratio = applied / rated if rated else 0.0
    value = (ratio ** m) + 1.0
    formula = f"π = (工作/额定)^{m} + 1 = ({applied:g}/{rated:g})^{m} + 1"
    return value, formula, {"applied": applied, "rated": rated, "ratio": round(ratio, 4), "exponent": m}


def _pick_number(d: Dict[str, Any], *keys: str) -> Optional[float]:
    """从 dict 里按候选键名取第一个能转成数字的值。"""
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return None


def evaluate_chain(
    *,
    cat_spec: Dict[str, Any],
    cat_name: str,
    ambient_temp_c: float,
    stress: Dict[str, Any],
    rated: Dict[str, Any],
    env_mult: float,
    env_label: str,
    pi_q: float,
    quality_label: str,
    source_ref: str,
) -> List[FactorEval]:
    """求出一条完整的因子链。返回顺序固定：π_T → π_V → π_S → π_Q → π_E。

    cat_spec 里没有声明的因子不会出现在结果中（例如电阻没有 π_V，IC 没有 π_S）。
    """
    factors: List[FactorEval] = []

    # ---- 1. 温度因子 ----------------------------------------------------
    temp_spec = cat_spec.get("pi_T")
    delta_t_default = float(cat_spec.get("default_delta_t_c", 0.0))
    delta_t_raw = _pick_number(stress, "temp_rise_c", "delta_t_c")
    if delta_t_raw is None:
        delta_t = delta_t_default
        delta_is_default = True
    else:
        delta_t = delta_t_raw
        delta_is_default = False
    t_op = ambient_temp_c + delta_t

    if temp_spec:
        model = temp_spec.get("formula", "power_law")
        if model == "arrhenius":
            value, formula, inputs = eval_arrhenius(temp_spec, t_op)
        else:
            value, formula, inputs = eval_power_law(temp_spec, t_op)
        inputs["delta_t_c"] = round(delta_t, 2)
        inputs["delta_t_source"] = "默认温升" if delta_is_default else "用户输入"
        name, _explain = FACTOR_LABELS["pi_T"]
        factors.append(
            FactorEval(
                key="pi_T",
                name=name,
                value=value,
                formula=formula,
                inputs=inputs,
                source=source_ref,
                is_default=delta_is_default,
                note="" if not delta_is_default else f"器件自升温未提供，按 {cat_name} 默认温升 {delta_t:g}°C 估算",
            )
        )

    # ---- 2. 电压应力因子 ------------------------------------------------
    v_spec = cat_spec.get("pi_V")
    if v_spec:
        applied_v = _pick_number(stress, "voltage", "voltage_applied", "v")
        rated_v = _pick_number(rated, "voltage", "voltage_rated", "vr")
        name, _explain = FACTOR_LABELS["pi_V"]
        if applied_v is not None and rated_v:
            value, formula, inputs = eval_power_plus_one(v_spec, applied_v, rated_v)
            factors.append(
                FactorEval(
                    key="pi_V", name=name, value=value, formula=formula, inputs=inputs,
                    source=source_ref, is_default=False,
                )
            )
        else:
            factors.append(
                FactorEval(
                    key="pi_V", name=name, value=1.0,
                    formula="π_V = 1.0（缺工作电压或额定电压，等效不修正）",
                    inputs={"applied": applied_v, "rated": rated_v},
                    source=source_ref, is_default=True,
                    note="未提供电压应力数据，本项按 1.0 处理。这是偏乐观的假设，建议补录额定电压与工作电压。",
                )
            )

    # ---- 3. 功率/电应力因子 ---------------------------------------------
    s_spec = cat_spec.get("pi_S")
    if s_spec:
        applied_p = _pick_number(stress, "power", "current", "power_applied")
        rated_p = _pick_number(rated, "power", "current", "power_rated")
        name, _explain = FACTOR_LABELS["pi_S"]
        if applied_p is not None and rated_p:
            value, formula, inputs = eval_power_plus_one(s_spec, applied_p, rated_p)
            factors.append(
                FactorEval(
                    key="pi_S", name=name, value=value, formula=formula, inputs=inputs,
                    source=source_ref, is_default=False,
                )
            )
        else:
            factors.append(
                FactorEval(
                    key="pi_S", name=name, value=1.0,
                    formula="π_S = 1.0（缺功率/电流应力数据，等效不修正）",
                    inputs={"applied": applied_p, "rated": rated_p},
                    source=source_ref, is_default=True,
                    note="未提供功率应力数据，本项按 1.0 处理，结果偏乐观。",
                )
            )

    # ---- 4. 质量因子（查表）---------------------------------------------
    name, _explain = FACTOR_LABELS["pi_Q"]
    factors.append(
        FactorEval(
            key="pi_Q", name=name, value=pi_q,
            formula=f"π_Q = 查表({quality_label}) = {pi_q:g}",
            inputs={"quality_level": quality_label},
            source=source_ref,
        )
    )

    # ---- 5. 环境因子（查表）---------------------------------------------
    name, _explain = FACTOR_LABELS["pi_E"]
    factors.append(
        FactorEval(
            key="pi_E", name=name, value=env_mult,
            formula=f"π_E = 查表({env_label}) = {env_mult:g}",
            inputs={"environment": env_label},
            source=source_ref,
        )
    )

    return factors


def describe_factor(key: str) -> Dict[str, str]:
    """给前端 Hover 提示用：返回 {label, explain}。"""
    label, explain = FACTOR_LABELS.get(key, (key, ""))
    return {"label": label, "explain": explain}
