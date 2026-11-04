"""
core/reliability/parts_stress.py — 零件应力法（Parts Stress）

【这个模块做什么】
比计数法细一档：对每个零件，用**实际工作条件**（工作电压、功率、温升）修正失效率。
同一个 BOM，应力法给出的 MTBF 通常比计数法高 1.5~3 倍，因为它不再假设"典型恶劣条件"。

【在整条流程中的位置】
    BOM + 分类 + 每个零件的工作应力/额定值 + 环境温度 → 本模块 → 整机 λ

【公式】
    λ_零件(FIT) = N × λ_b × π_T × π_V × π_S × π_Q × π_E
        N   用量
        λ_b 基础失效率（= 参数库 λ_g × 应力法基准系数；系数 <1 体现"应力法比计数法精细，不额外保守"）
        各项 π 因子由 factor_chain 按参数库声明求出；未提供应力数据的因子取 1.0 并标记为默认。

【为什么要区分"额定值"和"工作应力"】
    π_V = (工作电压/额定电压)^m + 1
    工作电压是你电路里实际加的电压；额定电压是器件手册标的耐压。
    这两个数一个来自设计、一个来自选型，混用会让降额检查与失效率同时错。
    本模块只吃"工作应力"（stress），降额模块负责把 stress 和 rated 对比。

【新手最容易踩的坑】
  1. 忘了加 273.15：用摄氏度直接代入 Arrhenius 会得到离谱的数（比如 π_T = 1e-15）。
     本模块内部统一用开尔文，转换在 factor_chain 里做。
  2. 把"环境温度"当成"器件温度"：器件自己会发热，T_op = T_环境 + 自升温。
     未提供温升时按类别默认值估算，并在追溯中标注为 default——这类假设必须可查。
  3. 用量没乘：10 只电容的失效率是单只的 10 倍，漏乘会让整机 MTBF 虚高一个量级。
"""

from __future__ import annotations

from typing import List

from ..models import AssessmentResult, Assumption, PartInput, PartResult, TraceStep
from ..standards.factor_chain import evaluate_chain
from ..standards.loader import ParamSet
from . import aggregate
from .rbd import build_rbd


def assess(parts: List[PartInput], assumption: Assumption, params: ParamSet) -> AssessmentResult:
    """对一份 BOM 执行零件应力法预计。"""
    results: List[PartResult] = []
    env_mult = params.env_mult(assumption.environment)
    env_label = params.env_label(assumption.environment)
    pi_q = params.pi_q(assumption.quality_level)
    quality_label = params.quality_label(assumption.quality_level)

    for p in parts:
        if not p.category_code or not params.has_category(p.category_code):
            raise ValueError(
                f"零件 {p.part_number} 的分类「{p.category_code or '空'}」在参数库中不存在，"
                "请先在分类确认页完成归类"
            )

        cat = params.category(p.category_code)
        trace: List[TraceStep] = []
        step = 1

        # ---- 步骤 1：基础失效率 -------------------------------------------
        lambda_b = cat.lambda_g * params.stress_lambda_factor
        trace.append(
            TraceStep(
                step=step,
                name=f"基础失效率 λ_b（{cat.name}）",
                formula=(
                    f"λ_b = 表值 × 应力法系数 = {cat.lambda_g:g} × {params.stress_lambda_factor:g}"
                    f" = {lambda_b:g} FIT"
                ),
                inputs={
                    "category": cat.code,
                    "table_lambda": cat.lambda_g,
                    "stress_factor": params.stress_lambda_factor,
                    "standard": params.standard,
                },
                value=lambda_b,
                unit="FIT",
                source=params.source_ref,
            )
        )
        step += 1

        # ---- 步骤 2~n：求整条因子链 ---------------------------------------
        factors = evaluate_chain(
            cat_spec=cat.stress_spec,
            cat_name=cat.name,
            ambient_temp_c=assumption.ambient_temp_c,
            stress=p.stress or {},
            rated=p.rated or {},
            env_mult=env_mult,
            env_label=env_label,
            pi_q=pi_q,
            quality_label=quality_label,
            source_ref=params.source_ref,
        )

        factor_values = {}
        part_warnings: List[str] = []
        for f in factors:
            trace.append(TraceStep(**{k: v for k, v in f.as_trace_dict(step).items() if k != "step"}, step=step))
            factor_values[f.key] = round(f.value, 6)
            if f.is_default:
                part_warnings.append(f"{f.name} 使用默认值：{f.note or '缺输入数据'}")
            step += 1

        # ---- 步骤 n+1：连乘 + 用量 ----------------------------------------
        product = 1.0
        for v in factor_values.values():
            product *= v
        lambda_unit = lambda_b * product
        lambda_part = lambda_unit * p.qty

        factor_str = " × ".join(f"{k}={v:g}" for k, v in factor_values.items())
        trace.append(
            TraceStep(
                step=step,
                name="该零件合计失效率",
                formula=(
                    f"λ_零件 = λ_b × ({factor_str}) × 用量\n"
                    f"        = {lambda_b:g} × {product:.4f} × {p.qty} = {lambda_part:.6f} FIT"
                ),
                inputs={
                    "lambda_b": round(lambda_b, 6),
                    "factor_product": round(product, 6),
                    "qty": p.qty,
                    "lambda_unit": round(lambda_unit, 6),
                },
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
                lambda_b=lambda_b,
                factors=factor_values,
                lambda_part=lambda_part,
                trace=trace,
                warnings=part_warnings,
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
        disclaimers=[
            (
                "本次为零件应力法（Parts Stress）：已计入温度、电压/功率应力。"
                "未提供应力的零件按默认值处理（追溯明细中标为「默认」），结果偏乐观。"
            )
        ],
    )
