"""
tests/test_core.py — 计算核心的单元测试

【覆盖重点（对应需求"单元测试重点覆盖"四项）】
1. 分类匹配（含边界 case 分流、负向关键词、单位归一化）
2. 失效率计算（因子组合、单调性、用量线性、追溯自洽）
3. 磨损寿命公式（10℃ 法则的严格性、次数折算、缺数据兜底）
4. 降额判定（四档边界值）
另加：存活率/MTBF 互推、RBD 并联、参数库一致性。

【为什么这些测试值得写】
可靠性代码的错误往往是"静默"的：公式写反了不会抛异常，只会给出一个看起来合理的数字。
例如 273.15 忘了加、qty 忘了乘、π_T 方向反了——这些都必须靠对拍手算值发现。
所以下面每个用例都尽量用"手算能算出来的数"做断言，而不是只断言"不为空"。
"""

from __future__ import annotations

import math

import pytest

from core.derating import checker
from core.models import Assumption, PartInput
from core.parse_spec import parse_spec
from core.reliability import parts_count, parts_stress, rbd, survival
from core.standards.factor_chain import K_BOLTZMANN_EV, evaluate_chain
from core.standards.loader import load_category_kb, load_derating_rules, load_param_set, load_wear_models
from core.wear import models as wear_models


@pytest.fixture(scope="module")
def mil():
    return load_param_set("MIL-217F")


@pytest.fixture(scope="module")
def tel():
    return load_param_set("TELCORDIA_SR332")


# ---------------------------------------------------------------------------
# 1. 参数库与解析
# ---------------------------------------------------------------------------


def test_param_set_consistency(mil, tel):
    assert mil.standard == "MIL-217F"
    assert len(mil.categories) >= 30
    # 两个标准的类别集合应大体一致，否则"双标准对比"会缺项
    missing = set(mil.categories) - set(tel.categories)
    assert not missing, f"Telcordia 参数库缺少类别：{missing}"
    # 环境倍率必须单调（越严酷越大），否则敏感性曲线会出现反直觉的坑
    envs = sorted(mil.environments.items(), key=lambda kv: kv[1]["mult"])
    assert envs[0][0] == "C"
    assert mil.env_mult("GB") == 1.0


def test_parse_spec_units():
    """单位写法差异必须被归一化到同一个数。"""
    cases = [
        ("CAP CER 0.1uF 50V X7R 0603", {"capacitance_uf": 0.1, "voltage": 50.0}),
        ("电容 100nF/50V", {"capacitance_uf": 0.1, "voltage": 50.0}),
        ("CAP 220pF 50V", {"capacitance_uf": 0.00022}),
        ("RES 10KΩ 1% 1/10W 0603", {"power": 0.1}),
        ("RELAY 电气寿命10万次", {"cycles": 100000.0}),
    ]
    for desc, expected in cases:
        got = parse_spec(desc)
        for k, v in expected.items():
            assert k in got, f"{desc} 未解析出 {k}"
            assert got[k] == pytest.approx(v, rel=1e-6), f"{desc} 的 {k} 解析错误：{got[k]}"


def test_parse_spec_reference_temp_not_max():
    """@40℃ 是寿命参考温度，不能被当成额定最高温度。"""
    got = parse_spec("FAN 4010 5V 0.1A L10=30000h@40℃")
    assert got["ref_temp_c"] == 40.0
    assert "temp_max_c" not in got
    assert got["life_h"] == 30000.0


# ---------------------------------------------------------------------------
# 2. 分类匹配
# ---------------------------------------------------------------------------


def test_classify_three_way_split():
    """高度相似的三兄弟必须分开；缺信息进待确认；完全无关进未识别。"""
    from app.services.kb import build_kb  # noqa: F401  (仅在集成环境可用)
    pytest.importorskip("sqlalchemy")
    from core.classify.engine import Classifier

    clf = Classifier(load_category_kb())

    r = clf.classify("CAP CER 0.1uF 50V X7R 0603")
    assert r.status == "auto" and r.best.code == "CAP_CER"

    r = clf.classify("CAP FILM 0.1uF 50V CBB22")
    assert r.status == "auto" and r.best.code == "CAP_FILM"

    r = clf.classify("CAP ALU 0.1uF 50V 105℃")
    assert r.status == "auto" and r.best.code == "CAP_ALU"

    r = clf.classify("电容 0.1uF 50V 0603")
    assert r.status == "pending_review", r.reason

    r = clf.classify("定制五金支架 SUS304 折弯件")
    assert r.status == "unrecognized"


def test_classify_negative_keyword_blocks_wrong_category():
    """陶瓷电容不该被铝电解的『电解』『uF』拉过去。"""
    from core.classify.engine import Classifier

    clf = Classifier(load_category_kb())
    r = clf.classify("MLCC 10uF 16V X5R 0805")
    assert r.best.code == "CAP_CER"
    cand = {c.code: c for c in r.candidates}
    if "CAP_ALU" in cand:
        assert cand["CAP_ALU"].score < cand["CAP_CER"].score


# ---------------------------------------------------------------------------
# 3. 失效率计算
# ---------------------------------------------------------------------------


def _parts():
    return [
        PartInput(1, "P1", "CAP ALU 1000uF 25V 105℃ 2000h", 2, "CAP_ALU", {"voltage": 20.0}, {"voltage": 25}),
        PartInput(2, "P2", "RES 10KΩ 1% 1/10W 0603", 10, "RES_THICK", {"power": 0.05}, {"power": 0.1}),
    ]


def test_parts_count_formula(mil):
    """手算：λ = Σ(qty × λ_g × π_E × π_Q)。"""
    a = Assumption(ambient_temp_c=40, duty_cycle=1.0, standard="MIL-217F", mode="parts_count")
    res = parts_count.assess(_parts(), a, mil)

    expect = 0.0
    for p in _parts():
        cat = mil.category(p.category_code)
        expect += p.qty * cat.lambda_g * mil.env_mult("GB") * mil.pi_q("commercial")
    assert res.lambda_total_fit == pytest.approx(expect, rel=1e-9)
    assert res.mtbf_hours == pytest.approx(1e9 / expect, rel=1e-9)


def test_parts_count_ignores_temperature(mil):
    """MIL 计数法不含 π_T：改温度不应改变结果（这是标准口径，不是 bug）。"""
    a1 = Assumption(ambient_temp_c=25, duty_cycle=1.0, mode="parts_count")
    a2 = Assumption(ambient_temp_c=70, duty_cycle=1.0, mode="parts_count")
    r1 = parts_count.assess(_parts(), a1, mil)
    r2 = parts_count.assess(_parts(), a2, mil)
    assert r1.lambda_total_fit == pytest.approx(r2.lambda_total_fit, rel=1e-9)


def test_quality_level_monotonic(mil):
    """质量等级越好，失效率必须越低。"""
    vals = []
    for q in ["commercial", "industrial", "automotive", "military"]:
        a = Assumption(quality_level=q, duty_cycle=1.0, mode="parts_count")
        vals.append(parts_count.assess(_parts(), a, mil).lambda_total_fit)
    assert vals == sorted(vals, reverse=True), vals


def test_qty_linearity(mil):
    """用量翻倍，失效率翻倍。"""
    a = Assumption(duty_cycle=1.0, mode="parts_count")
    base = parts_count.assess(_parts(), a, mil).lambda_total_fit

    doubled = [
        PartInput(1, "P1", "CAP ALU", 4, "CAP_ALU", {"voltage": 20.0}, {"voltage": 25}),
        PartInput(2, "P2", "RES 10KΩ", 20, "RES_THICK", {"power": 0.05}, {"power": 0.1}),
    ]
    assert parts_count.assess(doubled, a, mil).lambda_total_fit == pytest.approx(base * 2, rel=1e-9)


def test_parts_stress_temperature_increases_failure_rate(mil):
    a_low = Assumption(ambient_temp_c=25, duty_cycle=1.0, mode="parts_stress")
    a_high = Assumption(ambient_temp_c=70, duty_cycle=1.0, mode="parts_stress")
    low = parts_stress.assess(_parts(), a_low, mil).lambda_total_fit
    high = parts_stress.assess(_parts(), a_high, mil).lambda_total_fit
    assert high > low


def test_power_law_pi_t_hand_calc():
    """π_T = ((T+273.15)/(T_ref+273.15))^n，手算对拍。"""
    spec = {"pi_T": {"formula": "power_law", "ref_temp_c": 25.0, "exponent": 5.0}, "default_delta_t_c": 0.0}
    f = evaluate_chain(
        cat_spec=spec, cat_name="测试", ambient_temp_c=55.0, stress={}, rated={},
        env_mult=1.0, env_label="GB", pi_q=1.0, quality_label="商用", source_ref="test",
    )[0]
    expected = ((55 + 273.15) / (25 + 273.15)) ** 5
    assert f.value == pytest.approx(expected, rel=1e-12)
    assert f.key == "pi_T"


def test_arrhenius_pi_t_hand_calc():
    """Arrhenius 必须用开尔文；温度升高 → π_T > 1。"""
    spec = {"pi_T": {"formula": "arrhenius", "ea_ev": 0.35, "ref_temp_c": 40.0}, "default_delta_t_c": 0.0}
    f = evaluate_chain(
        cat_spec=spec, cat_name="测试", ambient_temp_c=85.0, stress={}, rated={},
        env_mult=1.0, env_label="GB", pi_q=1.0, quality_label="商用", source_ref="test",
    )[0]
    expected = math.exp((0.35 / K_BOLTZMANN_EV) * (1 / (40 + 273.15) - 1 / (85 + 273.15)))
    assert f.value == pytest.approx(expected, rel=1e-9)
    assert f.value > 1.0


def test_missing_stress_marked_default(mil):
    """缺应力数据时因子取 1.0，且必须标记 is_default（报告要能看出这一处偏乐观）。"""
    parts = [PartInput(1, "P1", "CAP CER 0.1uF 50V 0603", 1, "CAP_CER", {}, {})]
    res = parts_stress.assess(parts, Assumption(duty_cycle=1.0, mode="parts_stress"), mil)
    defaults = [s for s in res.parts[0].trace if s.is_default]
    assert defaults, "缺数据时应有 is_default 标记"
    assert all(d.value == 1.0 for d in defaults if d.name.startswith("电压") or d.name.startswith("功率"))


def test_trace_self_consistent(mil):
    """追溯里的因子连乘必须等于最终的 λ_零件 / qty。"""
    res = parts_stress.assess(_parts(), Assumption(duty_cycle=1.0, mode="parts_stress"), mil)
    for p in res.parts:
        product = 1.0
        for v in p.factors.values():
            product *= v
        assert p.lambda_part == pytest.approx(p.lambda_b * product * p.qty, rel=1e-9)
        assert len(p.trace) == len(p.factors) + 2  # λ_b + 各因子 + 合计


def test_unclassified_part_raises(mil):
    """未分类零件必须报错，不能静默跳过（跳过会让 MTBF 虚高）。"""
    parts = [PartInput(1, "P1", "未知件", 1, "", {}, {})]
    with pytest.raises(ValueError, match="分类"):
        parts_count.assess(parts, Assumption(duty_cycle=1.0), mil)


# ---------------------------------------------------------------------------
# 4. 存活率 / RBD
# ---------------------------------------------------------------------------


def test_survival_formula():
    # MTBF = 1e6 h，工作 5 年 × 8760 h → R = exp(-43800/1e6)
    assert survival.survival(1000.0, 43800) == pytest.approx(math.exp(-0.0438), rel=1e-12)
    assert survival.operating_hours(5, 8 / 24) == pytest.approx(5 * 8760 * 8 / 24)
    assert survival.mtbf_from_fit(100.0) == pytest.approx(1e7)


def test_survival_inverse():
    """由目标存活率反推的年限，代回 R(t) 应恰好等于目标值。"""
    lam = 500.0
    years = survival.years_to_reach_survival(lam, 0.9, 1.0)
    assert survival.survival_at_years(lam, years, 1.0) == pytest.approx(0.9, rel=1e-9)


def test_rbd_parallel_better_than_series():
    """两件并联的等效 λ 必须小于串联相加；单件"冗余"退化为串联。"""
    lam_eq, r = rbd.group_equivalent_lambda([100.0, 100.0], 8760.0)
    assert lam_eq < 200.0
    assert 0.9 < r <= 1.0

    parts = [
        __import__("core.models", fromlist=["PartResult"]).PartResult(1, "P1", 1, "CAP_ALU", "铝电解", 1.0, {}, 100.0),
        __import__("core.models", fromlist=["PartResult"]).PartResult(2, "P2", 1, "CAP_ALU", "铝电解", 1.0, {}, 100.0),
        __import__("core.models", fromlist=["PartResult"]).PartResult(3, "P3", 1, "CAP_ALU", "铝电解", 1.0, {}, 50.0),
    ]
    model = rbd.build_rbd(parts, {1: "G1", 2: "G1", 3: "G2"}, 8760.0)
    assert len(model.groups) == 1, "单成员组应退化为串联，不产生冗余组"
    assert model.lambda_total < model.lambda_total_without_redundancy


# ---------------------------------------------------------------------------
# 5. 磨损寿命
# ---------------------------------------------------------------------------


def _wear(desc, cat, stress=None, rated=None, ambient=55.0):
    parts = [PartInput(1, "W1", desc, 1, cat, stress or {}, rated or {})]
    cfg = load_wear_models()
    return wear_models.assess_wear(parts, Assumption(ambient_temp_c=ambient, duty_cycle=1.0), cfg)[0]


def test_cap_life_double_every_10c():
    """10℃ 法则：温度低 10℃，寿命刚好翻倍（K_V=1 时）。"""
    a = _wear("CAP ALU 1000uF 25V 105℃ 2000h", "CAP_ALU", {"voltage": 10.0, "temp_rise_c": 0}, {"voltage": 25}, ambient=65)
    b = _wear("CAP ALU 1000uF 25V 105℃ 2000h", "CAP_ALU", {"voltage": 10.0, "temp_rise_c": 0}, {"voltage": 25}, ambient=55)
    assert b.life_hours == pytest.approx(a.life_hours * 2, rel=1e-9)
    assert a.life_hours == pytest.approx(2000 * 2 ** ((105 - 65) / 10), rel=1e-9)


def test_cap_voltage_factor_penalises_overstress():
    """电压用到额定 96% 时寿命应打 0.44 折，而不是 1.0。"""
    ok = _wear("CAP ALU 1000uF 25V 105℃ 2000h", "CAP_ALU", {"voltage": 20.0}, {"voltage": 25})
    bad = _wear("CAP ALU 1000uF 25V 105℃ 2000h", "CAP_ALU", {"voltage": 24.0}, {"voltage": 25})
    assert bad.life_hours < ok.life_hours
    assert bad.inputs["K_V"] == pytest.approx(1.0 - (0.96 - 0.8) * 3.5, rel=1e-6)


def test_relay_cycle_count():
    """继电器：10 万次 / (200 次/日 × 365) ≈ 1.37 年。"""
    w = _wear("RELAY 5V 10A 电气寿命10万次", "RELAY", {"daily_ops": 200}, {"cycles": 100000})
    assert w.life_years == pytest.approx(100000 / (200 * 365), rel=1e-6)


def test_wear_defaults_flagged():
    """缺数据时必须走保守默认值并记录下来（不能悄悄猜一个数）。"""
    w = _wear("CAP ALU 470uF 35V", "CAP_ALU", {}, {})
    assert w.using_defaults, "缺 L0/T_max 时应记录默认值"
    assert w.life_hours > 0


def test_wear_limiting_flag():
    parts = [
        PartInput(1, "W1", "CAP ALU 1000uF 25V 105℃ 2000h", 1, "CAP_ALU", {}, {"voltage": 25}),
        PartInput(2, "W2", "FAN 4010 L10=70000h@40℃", 1, "FAN", {}, {}),
    ]
    res = wear_models.assess_wear(parts, Assumption(ambient_temp_c=60, duty_cycle=1.0), load_wear_models())
    assert res[0].is_limiting and res[0].life_years <= res[1].life_years


# ---------------------------------------------------------------------------
# 6. 降额
# ---------------------------------------------------------------------------


def _derate(desc, cat, stress, rated):
    cfg = load_derating_rules()
    p = PartInput(1, "D1", desc, 1, cat, stress, rated)
    return checker.check_part(p, Assumption(ambient_temp_c=55), cfg)


def test_derating_four_levels():
    """电容电压上限 80%、缓冲 10% → 三段：<70% 满足、70~80% 接近、>80% 超限。"""
    cases = [
        ({"voltage": 25 * 0.65}, "pass"),
        ({"voltage": 25 * 0.75}, "marginal"),
        ({"voltage": 25 * 0.90}, "violation"),
    ]
    for stress, want in cases:
        rows = _derate("CAP ALU 1000uF 25V 105℃", "CAP_ALU", stress, {"voltage": 25, "temp_max_c": 105})
        v = [r for r in rows if r.stress_type == "voltage"][0]
        assert v.verdict == want, (stress, v.verdict, v.ratio)


def test_derating_boundary_exact():
    """正好等于上限应判 marginal（不超限），不是 violation。"""
    rows = _derate("CAP ALU 1000uF 25V", "CAP_ALU", {"voltage": 20.0}, {"voltage": 25, "temp_max_c": 105})
    v = [r for r in rows if r.stress_type == "voltage"][0]
    assert v.ratio == pytest.approx(0.8)
    assert v.verdict == "marginal"


def test_derating_no_data():
    rows = _derate("CAP ALU 470uF", "CAP_ALU", {}, {})
    assert all(r.verdict == "no_data" for r in rows if r.stress_type == "voltage")


def test_derating_temperature_margin():
    """温度类用绝对余量：105℃ 的电容工作在 100℃ 应判接近（要求 ≤95℃）。"""
    rows = _derate("CAP ALU 1000uF 25V 105℃", "CAP_ALU", {"temp_rise_c": 45}, {"voltage": 20, "temp_max_c": 105})
    t = [r for r in rows if r.stress_type == "temperature"][0]
    assert t.verdict == "marginal"


# ---------------------------------------------------------------------------
# 7. 敏感性
# ---------------------------------------------------------------------------


def test_sensitivity_monotonic_in_temperature(mil):
    from core.sens import sweep as sens

    res = sens.sweep(_parts(), Assumption(duty_cycle=1.0, mode="parts_stress"), mil, "ambient_temp")
    mtbfs = [p.mtbf_hours for p in res.points]
    assert mtbfs == sorted(mtbfs, reverse=True), "温度升高 MTBF 必须单调下降"
    assert res.elasticity is not None and res.elasticity < 0
