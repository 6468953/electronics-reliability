"""
core/calc.py — 计算核心的总入口（门面）

【这个模块做什么】
Web 层（FastAPI）只需要认识一个函数：`evaluate()`。它内部负责：
    1. 按标准加载参数库；
    2. 跑可靠性预计（单标准 or 双标准）；
    3. 跑磨损寿命、降额检查；
    4. 需要时跑敏感性扫描；
    5. 全部序列化成前端能直接吃的 dict。

【在整条流程中的位置】
    FastAPI router → core.calc.evaluate() → dict → JSON 响应 → 前端图表/表格
                                          └→ core.report_ctx → PDF/XLSX

【为什么需要这一层】
如果让每个 router 自己拼装"先加载参数、再算这个、再算那个"，很快就会出现
"评估页和报告页口径不一致"。把编排收在一个函数里，是保证一致性的最省事办法。
同时它也保证了计算核心依然不依赖 Web 框架——router 可以换，这一层不动。
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional

from .derating import checker
from .models import AssessmentResult, Assumption, DeratingResult, PartInput, WearResult
from .reliability import parts_count, parts_stress, survival
from .sens import sweep as sens_sweep
from .standards.loader import load_derating_rules, load_param_set, load_wear_models
from .wear import models as wear_models
from .wear import ranking as wear_ranking


class CalcError(Exception):
    """计算无法进行（分类缺失、参数越界等）——这类错误要原样展示给用户。"""


def _check_assumption(a: Assumption) -> None:
    if a.duty_cycle <= 0 or a.duty_cycle > 1:
        raise CalcError("日通电占比必须在 (0, 1] 之间，例如 8 小时/日 = 0.333")
    if a.target_years <= 0:
        raise CalcError("目标年限必须大于 0")
    if not (0 < a.target_survival < 1):
        raise CalcError("目标存活率必须在 0~1 之间，例如 95% 填 0.95")
    if a.ambient_temp_c < -60 or a.ambient_temp_c > 150:
        raise CalcError("环境温度应在 -60 ~ 150°C 之间")


def _append_wear_warning(assessment: Dict[str, Any], wear: Dict[str, Any], assumption: Assumption) -> None:
    """把"磨损视角比目标还短"这类结论提升为一条预警。

    【为什么要在结果层做这件事】
    PASS/FAIL 只看随机失效（存活率 + MTBF 门槛）。一台设备的 MTBF 完全可能达标，
    而它的继电器 4.6 年就烧完了。如果只把磨损结论留在"磨损寿命"页，评审很容易只看
    绿色的 PASS 就签字。所以这里把它写成一条与"参数缺失"同级的预警，强制出现在结论区。
    """
    t_sys = wear.get("t_system_years")
    if t_sys is None:
        return
    if t_sys >= assumption.target_years:
        return
    assessment.setdefault("warnings", []).append(
        f"磨损视角的最短寿命 {t_sys:.1f} 年（{wear.get('limiting_mechanism', '')}）"
        f"低于目标 {assumption.target_years:g} 年。MTBF 判定通过并不代表整机寿命达标——"
        "随机失效与耗损失效是两条独立的失效路径，必须同时满足。请优先处理该磨损件"
        "（换长寿命料、降低其工作温度或减少动作次数）。"
    )


def run_assessment(parts: List[PartInput], assumption: Assumption, param_dir: Optional[str] = None) -> AssessmentResult:
    """按指定标准与模式跑一次预计。"""
    _check_assumption(assumption)
    if not parts:
        raise CalcError("BOM 中没有可计算的零件（请先完成分类）")

    params = load_param_set(assumption.standard, param_dir)
    if assumption.mode == "parts_stress":
        return parts_stress.assess(parts, assumption, params)
    return parts_count.assess(parts, assumption, params)


def evaluate(
    parts: List[PartInput],
    assumption: Assumption,
    *,
    with_wear: bool = True,
    with_derating: bool = True,
    with_sensitivity: bool = False,
    param_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """完整评估：预计 + 磨损 + 降额（+ 敏感性）。返回可直接 JSON 化的 dict。"""
    assessment = run_assessment(parts, assumption, param_dir)

    payload: Dict[str, Any] = {
        "assessment": to_dict(assessment),
        "survival_curve": [
            {"year": float(y), "r": round(survival.survival_at_years(assessment.lambda_total_fit, y, assumption.duty_cycle), 6)}
            for y in [0, 0.5, 1, 2, 3, 5, 7, 10, 15, 20]
        ],
        "assumptions": to_dict(assumption),
    }

    if with_wear:
        wear_cfg = load_wear_models(param_dir)
        wear = wear_models.assess_wear(parts, assumption, wear_cfg)
        payload["wear"] = wear_ranking.summarize(wear, assessment, assumption)
        payload["wear"]["disclaimer"] = wear_cfg.get("disclaimer", "")
        _append_wear_warning(payload["assessment"], payload["wear"], assumption)

    if with_derating:
        derating_cfg = load_derating_rules(param_dir)
        results = checker.check_all(parts, assumption, derating_cfg)
        payload["derating"] = {
            "summary": checker.summarize(results),
            "items": [to_dict(r) for r in results],
            "disclaimer": derating_cfg.get("disclaimer", ""),
            "source_ref": derating_cfg.get("source_ref", ""),
        }

    if with_sensitivity:
        params = load_param_set(assumption.standard, param_dir)
        temp_sweep = sens_sweep.sweep(parts, assumption, params, "ambient_temp")
        payload["sensitivity"] = {
            "temp": to_dict(temp_sweep),
            "ranking": sens_sweep.rank_assumptions(parts, assumption, params),
        }

    return payload


def compare_standards(
    parts: List[PartInput], assumption: Assumption, param_dir: Optional[str] = None
) -> Dict[str, Any]:
    """双标准同时计算，供页面/报告并排对比。

    工程上为什么要同时跑两套：两套参数体系的口径不同（MIL 更保守、Telcordia 更贴近电信设备
    现场数据），单独看任何一套都可能被质疑"是不是标准选得有利"。并排展示差异，
    比只报一个数更专业，也更诚实。
    """
    out: Dict[str, Any] = {"mode": assumption.mode, "standards": {}}
    for std in ("MIL-217F", "TELCORDIA_SR332"):
        a = Assumption(**{**asdict(assumption), "standard": std})
        res = run_assessment(parts, a, param_dir)
        out["standards"][std] = {
            "lambda_total_fit": res.lambda_total_fit,
            "mtbf_hours": res.mtbf_hours,
            "r_at_target": res.r_at_target,
            "verdict": res.verdict,
            "param_version": res.param_version,
            "display_name": load_param_set(std, param_dir).display_name,
        }

    mil = out["standards"]["MIL-217F"]["lambda_total_fit"]
    tel = out["standards"]["TELCORDIA_SR332"]["lambda_total_fit"]
    if mil and tel:
        out["ratio_mil_over_telcordia"] = round(mil / tel, 2)
        out["note"] = (
            f"MIL-217F 给出的失效率是 Telcordia 的 {mil/tel:.2f} 倍。"
            "这是常见现象：MIL 面向航空航天的保守估计，Telcordia 基于电信设备的现场数据。"
            "两套结果都不算错，报告应同时列出并说明取用哪一套及理由。"
        )
    return out


def to_dict(obj: Any) -> Any:
    """dataclass → dict，递归处理列表与嵌套。"""
    if is_dataclass(obj):
        return {k: to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, float):
        # JSON 标准不支持 NaN / Infinity，必须转成 null，否则前端 JSON.parse 直接失败。
        if obj != obj or obj in (float("inf"), float("-inf")):
            return None
        return obj
    return obj
