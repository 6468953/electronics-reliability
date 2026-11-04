"""
core/models.py — 计算核心的「数据契约」

【这个模块做什么】
把 Web 层（数据库里的 ORM 对象、JSON 请求）和计算核心（纯公式）之间需要传递的所有
数据结构，用 dataclass 固定下来。计算核心只认这些 dataclass，不认 SQLAlchemy 也不认
Pydantic，这样才能被 pytest 和命令行单独调用。

【在整条流程中的位置】
    BOM 表 → (Web 层翻译) → PartInput[]  ┐
    页面表单 → (Web 层翻译) → Assumption   ├→ core.calc.assess() → AssessmentResult → 报告/图表
    参数库 JSON → ParamSet               ┘

【为什么需要它】
如果计算函数直接接收 ORM 对象，那么每改一次数据库字段、每加一层缓存，公式代码都得跟着改，
而且没法离线跑。用 dataclass 做一层"防火墙"后，公式代码可以被冻结、被测试、被复现。

【给电子工程背景读者的提示】
本文件里的名词：
  - FIT  ：Failure In Time，每 10^9 小时（约 11.4 万年）的失效次数。10 FIT = 平均 1 亿小时坏一次。
  - MTBF ：Mean Time Between Failures，平均无故障时间（小时）。纯随机失效假设下 MTBF = 1e9 / 总FIT。
  - λ    ：失效率（failure rate），单位 1/小时；工程上常直接用 FIT 表达。
  - π 因子：乘法修正项。π_Q（质量）、π_E（环境）、π_T（温度）、π_V（电压应力）、π_S（功率应力）。
            π = 1 表示"与基准条件相同"；π = 3 表示"比基准差 3 倍"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 输入侧
# ---------------------------------------------------------------------------


@dataclass
class PartInput:
    """BOM 中的一行（一个"零件位"）。

    注意区分「零件」和「零件种类」：一行代表某个料号在板上用了 qty 个（如 8 个 0.1uF 电容），
    失效率是按 qty 累加的，所以 qty 是这里的关键字段。
    """

    part_id: int                      # 数据库 bom_items.id，用于把结果对回表格
    part_number: str                  # 料号
    description: str                  # 规格描述（分类引擎的输入，也是人工核对依据）
    qty: int                          # 用量
    category_code: str                # 已确认的分类编码，如 CAP_ALU；未分类时为空串
    # 工作应力（Parts Stress 模式用）。缺省即视为"未编辑"，由类别默认值兜底。
    # 例：{"voltage": 12.0, "current": 0.05, "power": 0.1, "temp_rise_c": 8.0}
    stress: Dict[str, float] = field(default_factory=dict)
    # 额定值（降额检查 + 磨损计算用），从描述解析或人工补录。
    # 例：{"voltage": 25.0, "capacitance_uf": 1000.0, "temp_max_c": 105.0, "life_h": 2000.0}
    rated: Dict[str, float] = field(default_factory=dict)
    # 冗余组：相同字符串的零件在可靠性框图中视为"并联冗余"（任一存活即系统存活）。
    redundancy_group: Optional[str] = None
    redundancy_note: Optional[str] = None


@dataclass
class Assumption:
    """评估假设（模块四要求的"四参数"+ 目标）。整份报告的可信度全押在这几个数上。"""

    environment: str = "GB"           # 环境类别，见 ParamSet.environments
    ambient_temp_c: float = 40.0      # 环境温度（°C）
    quality_level: str = "commercial"  # 质量等级
    duty_cycle: float = 8.0 / 24.0    # 日通电占比（8h/日 ≈ 0.333）
    target_years: float = 5.0         # 目标年限
    target_survival: float = 0.95     # 目标存活率 R(t)
    mtbf_threshold_hours: Optional[float] = None  # 可选的 MTBF 门槛（如 430000 / 1000000）
    standard: str = "MIL-217F"        # "MIL-217F" | "TELCORDIA_SR332"
    mode: str = "parts_count"        # "parts_count"（零件计数法）| "parts_stress"（零件应力法）


# ---------------------------------------------------------------------------
# 计算追溯：每一步都留痕，报告和前端「计算明细」抽屉共用
# ---------------------------------------------------------------------------


@dataclass
class TraceStep:
    """一步计算。刻意做成结构化的（不是拼好的字符串），这样前端能排版、能高亮、能导出。"""

    step: int
    name: str                          # 这一步在算什么，如"温度因子 π_T"
    formula: str                       # 公式原文，如 "π_T = ((T_op+273)/313)^5"
    inputs: Dict[str, Any]             # 代入了哪些值
    value: float                       # 算出来的结果
    unit: str = "-"                    # 单位，多数因子是无量纲，写 "-"
    source: str = ""                   # 依据来源：标准名 + 章节/表号
    is_default: bool = False           # 是否用了"默认值/兜底值"（报告里要标出来，便于追责）
    note: str = ""                     # 补充说明，例如"为何这一项取了 1.0"


@dataclass
class PartResult:
    """单个零件的可靠性计算结果。"""

    part_id: int
    part_number: str
    qty: int
    category_code: str
    category_name: str
    lambda_b: float                    # 基础失效率（FIT）
    factors: Dict[str, float]           # 各 π 因子{ "pi_T": 1.87, "pi_Q": 3.0, ... }
    lambda_part: float                  # 该零件（含 qty）的总失效率（FIT）
    trace: List[TraceStep] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    is_standard: bool = True            # False = 该类目不在此标准覆盖范围内（λ 为工程假设值）


@dataclass
class RedundancyGroupResult:
    """一个并联冗余组的等效结果（可靠性框图 / RBD）。

    并联的含义：k 个零件同时工作，只要有一个活着系统就活着。
    理论收益是 λ 大幅下降；但前提是"共因失效（同一个原因同时干掉所有冗余件）可忽略"，
    现实中电源浪涌、过热、同一批次缺陷都会同时命中，所以收益往往没算的那么大。
    """

    group: str
    member_ids: List[int]
    member_lambda_sum: float           # 如果按串联算（无冗余）的合计 λ
    lambda_equiv: float                # 并联折算后的等效 λ
    r_group: float                      # 在评估时间点的组存活率


@dataclass
class AssessmentResult:
    """一次完整评估的结果。这是报告、图表、判定全部的上游数据。"""

    standard: str
    mode: str
    param_version: str
    engine_version: str
    # 整机
    lambda_total_fit: float
    mtbf_hours: float
    r_at_target: float                 # 目标年限（按 duty 折算）的存活率
    operating_hours: float             # 目标年限对应的实际通电小时数
    verdict: str                       # "PASS" / "FAIL" / "NA"
    verdict_reasons: List[str] = field(default_factory=list)
    parts: List[PartResult] = field(default_factory=list)
    redundancy: List[RedundancyGroupResult] = field(default_factory=list)
    top_contributors: List[Dict[str, Any]] = field(default_factory=list)  # 短板排序
    warnings: List[str] = field(default_factory=list)
    disclaimer: str = ""


# ---------------------------------------------------------------------------
# 磨损 / 降额 / 敏感性
# ---------------------------------------------------------------------------


@dataclass
class WearResult:
    """一个磨损件的寿命估算结果。

    这里回答的是"能用多久"，而不是"多久坏一次"——两者是不同的问题：
      - MTBF 说随机失效的间隔（指数分布，与时间无关的常数风险）；
      - 磨损寿命说某个机理必然把件耗死的时间（威布尔/确定性，随时间递增的风险）。
    """

    part_id: int
    part_number: str
    description: str
    category_code: str
    mechanism: str                     # electrolytic_dryout / fan_bearing_L10 / ...
    mechanism_label: str               # 中文名，给界面和报告用
    life_hours: float                  # 估算寿命（小时）
    life_years: float                  # 折算年限（按 duty_cycle）
    formula: str
    inputs: Dict[str, Any]
    using_defaults: List[str] = field(default_factory=list)  # 哪些输入是兜底默认值
    note: str = ""
    is_limiting: bool = False          # 是否为全机最短寿命（限制项）


@dataclass
class DeratingResult:
    """一个零件的降额判定。verdict: pass / marginal / violation / no_data"""

    part_id: int
    part_number: str
    category_code: str
    category_name: str
    stress_type: str                   # voltage / current / power / temperature
    rated_value: Optional[float]
    applied_value: Optional[float]
    ratio: Optional[float]             # applied / rated
    max_ratio: float                   # 规范上限，如 0.8
    warn_ratio: float
    verdict: str
    rule_source: str = ""
    note: str = ""


@dataclass
class SensitivityPoint:
    x: float
    label: str
    mtbf_hours: float
    lambda_total_fit: float


@dataclass
class SensitivityResult:
    variable: str
    variable_label: str
    x_unit: str
    points: List[SensitivityPoint]
    elasticity: Optional[float]        # 弹性系数 (ΔMTBF/MTBF)/(Δx/x)
    total_swing_pct: float             # 全区间 MTBF 变化幅度（%）
    conclusion: str
