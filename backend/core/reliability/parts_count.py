"""
core/reliability/parts_count.py — 零件计数法（Parts Count）

【这个模块做什么】
最粗粒度、最常见的可靠性预计方法：凭"每个类别用了几只"就能算出整机失效率，不需要
任何电压/功率数据。适用于方案阶段、招投标阶段、以及还没有原理图的时候。

【在整条流程中的位置】
    BOM（类别 + 用量） + 环境 + 质量等级  →  本模块  →  整机 λ → aggregated 判定

【公式】

  MIL-HDBK-217F：
      λ_整机(FIT) = Σ_i  N_i × λ_g,i × π_Q,i
        N_i    该零件用量
        λ_g,i  该类别在该环境下的通用失效率（基准环境 GB × 环境倍率）
        π_Q,i  质量因子

  Telcordia SR-332 Method I：
      λ_整机(FIT) = Σ_i  N_i × λ_G,i × π_T,i × π_Q,i × π_E,i
        Telcordia 的 Method I 本身就含温度项（以 40°C 为基准的 Arrhenius），
        所以即使"计数法"也要带 π_T；这与 MIL 的计数法不同，是两套标准的口径差异。

【必须讲清的两件事】
1. MIL 计数法【不做温度修正】。这是标准定义：它假设器件处于典型条件（约 40°C），
   用于"信息不足时的保守估计"。所以用户在界面上把温度从 25 调到 70 而 MTBF 不动，
   不是 bug。要看温度影响，请切到「零件应力法」。
2. 计数法的结果通常比应力法【保守 1.5~3 倍】（因为它假设的是通用条件）。

【术语】
  λ_g（General failure rate）：通用失效率，标准表格里按"类别 × 环境"给出的基准值。
  π_Q：质量因子，商用级通常 3.0 左右，军品级 1.0。
"""

from __future__ import annotations

from typing import List

from ..models import AssessmentResult, Assumption, PartInput, PartResult, TraceStep
from ..standards.factor_chain import eval_power_law, eval_arrhenius
from ..standards.loader import ParamSet
from . import aggregate
from .rbd import build_rbd


def _telcordia_pi_t(params: ParamSet, cat_spec: dict, t_op_c: float):
    """Telcordia 计数法的温度因子（Arrhenius，缺省按幂律兜底）。"""
    temp_spec = cat_spec.get("pi_T") or {"formula": "arrhenius", "ea_ev": 0.35, "ref_temp_c": 40.0}
    if temp_spec.get("formula") == "arrhenius":
        return eval_arrhenius(temp_spec, t_op_c)
    return eval_power_law(temp_spec, t_op_c)


def assess(
    parts: List[PartInput],
    assumption: Assumption,
    params: ParamSet,
) -> AssessmentResult:
    """对一份 BOM 执行零件计数法预计，返回整机评估结论。"""
    results: List[PartResult] = []
    env_mult = params.env_mult(assumption.environment)
    env_label = params.env_label(assumption.environment)
    pi_q = params.pi_q(assumption.quality_level)
    quality_label = params.quality_label(assumption.quality_level)

    for p in parts:
        if not p.category_code or not params.has_category(p.category_code):
            # 未分类的零件不能静默跳过——跳过会让 MTBF 凭空变好，是最危险的一类错误。
            raise ValueError(
                f"零件 {p.part_number} 的分类「{p.category_code or '空'}」在参数库中不存在，"
                "请先在分类确认页完成归类"
            )

        cat = params.category(p.category_code)
        trace: List[TraceStep] = []
        step = 1

        # ---- 步骤 1：查该类别的基础失效率（基准环境）----------------------
        trace.append(
            TraceStep(
                step=step,
                name=f"查基础失效率 λ_g（{cat.name}）",
                formula=f"λ_g = 参数表({params.standard}, {cat.code}) = {cat.lambda_g:g} FIT",
                inputs={"category": cat.code, "standard": params.standard, "version": params.version_tag},
                value=cat.lambda_g,
                unit="FIT",
                source=params.source_ref,
            )
        )
        step += 1

        # ---- 步骤 2：乘环境倍率 -------------------------------------------
        trace.append(
            TraceStep(
                step=step,
                name="环境修正 π_E",
                formula=f"λ_g(环境) = λ_g × π_E = {cat.lambda_g:g} × {env_mult:g}",
                inputs={"environment": env_label, "multiplier": env_mult},
                value=cat.lambda_g * env_mult,
                unit="FIT",
                source=params.source_ref,
            )
        )
        step += 1
        lambda_env = cat.lambda_g * env_mult

        factor_values = {"pi_E": env_mult}

        # ---- Telcordia 额外带温度因子（MIL 计数法不带，这是标准口径差异）----
        if params.standard == "TELCORDIA_SR332":
            delta_t = float(cat.stress_spec.get("default_delta_t_c", 0.0))
            t_op = assumption.ambient_temp_c + delta_t
            pi_t, formula, inputs = _telcordia_pi_t(params, cat.stress_spec, t_op)
            trace.append(
                TraceStep(
                    step=step,
                    name="温度因子 π_T",
                    formula=formula,
                    inputs=inputs,
                    value=pi_t,
                    unit="-",
                    source=params.source_ref,
                )
            )
            step += 1
            lambda_env *= pi_t
            factor_values["pi_T"] = pi_t

        # ---- 步骤 3：质量因子 ---------------------------------------------
        trace.append(
            TraceStep(
                step=step,
                name="质量因子 π_Q",
                formula=f"π_Q = 查表({quality_label}) = {pi_q:g}",
                inputs={"quality_level": quality_label},
                value=pi_q,
                unit="-",
                source=params.source_ref,
            )
        )
        step += 1
        factor_values["pi_Q"] = pi_q

        # ---- 步骤 4：乘用量得该零件的合计失效率 ---------------------------
        lambda_part = lambda_env * pi_q * p.qty
        trace.append(
            TraceStep(
                step=step,
                name="该零件合计失效率",
                formula=f"λ_零件 = λ_g(环境) × π_Q × 用量 = {lambda_env:g} × {pi_q:g} × {p.qty}",
                inputs={"lambda_env": round(lambda_env, 6), "pi_Q": pi_q, "qty": p.qty},
                value=lambda_part,
                unit="FIT",
                source=params.source_ref,
            )
        )

        results.append(
            PartResult(
                part_id=p.part_id,
                part_number=p.part_number,
                qty=p.qty,
                category_code=cat.code,
                category_name=cat.name,
                lambda_b=cat.lambda_g,
                factors=factor_values,
                lambda_part=lambda_part,
                trace=trace,
                warnings=[],
            )
        )

    t_op_hours = assumption.target_years * 8760.0 * max(0.0, min(1.0, assumption.duty_cycle))
    rbd = build_rbd(results, {p.part_id: p.redundancy_group for p in parts}, t_op_hours)

    return aggregate.finalize(
        parts=results,
        rbd_model=rbd,
        assumption=assumption,
        param_version=params.version_tag,
        engine_version=params.engine_version,
        disclaimers=(
            [
                "本次为零件计数法（Parts Count）：MIL 口径下不做温度修正，"
                "是按「类别 + 用量」的保守估计；若需要看温度与电压应力的影响，请改用零件应力法。"
            ]
            if params.standard == "MIL-217F"
            else [
                "本次为 Telcordia SR-332 Method I（计数法）：已含温度项（40°C 基准 Arrhenius），"
                "未启用老化因子与置信度上限修正。"
            ]
        ),
    )
