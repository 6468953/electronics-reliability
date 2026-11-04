"""
core/reliability/rbd.py — 可靠性框图（RBD）与冗余折算

【这个模块做什么】
把 BOM 里的零件按"串联 / 并联"两种关系组装成整机模型，算出**等效失效率**。

【在整条流程中的位置】
    PartResult[]（每个零件的 λ） → rbd.build_lambdas() → 整机 λ → survival.py → R(t)

【为什么需要它】
默认假设是"串联"：任何一个零件坏了，整机就坏。这是绝大多数消费电子产品的事实（除了
少数冗余设计）。但工程上常给关键件加冗余（两个电源并联、两条通信链路），
此时不能简单把 λ 相加——必须用并联的存活率公式。系统要能算出"加冗余能挽回多少"。

【核心公式与通俗解释】

1) 串联（series）
   R_sys = R1 × R2 × ... × Rn
   λ_sys = λ1 + λ2 + ... + λn            （失效率直接相加）
   直觉：串联就是"一个都不能坏"，所以风险累加。

2) 并联（parallel / 冗余）
   R_sys = 1 − (1−R1)(1−R2)...(1−Rn)     （全坏才坏）
   即：两个 90% 存活率的件并联，存活率 1 − 0.1×0.1 = 99%（而不是 90%）。
   等效失效率不能直接写成 λ1λ2/(λ1+λ2) 那种简单式子然后代进任意时间点，
   本模块的做法是：先在评估时间点 T 算出 R_group(T)，再用
       λ_eq = −ln(R_group) / T
   反推一个"等效恒定失效率"，这样可以和其他串联件一起累加。
   这是工程上的常用近似（把非指数分布拟合成指数分布），误差随 T 增大而上升，
   所以报告里会同时给出"关掉冗余时的 MTBF"作对照，让读者看到收益的量级而非精确值。

3) 为什么风险不在并联件上——共因失效（CCF）
   两路独立电源并联，理论上 MTBF 提升很大；但如果两路共用同一个输入滤波器和同一路市电，
   一次浪涌就能同时打坏两个。这叫共因失效，会让实际收益远低于计算值。
   本系统的 RBD 模型【忽略共因失效】，因此结果是收益上限，界面与报告强制提示这一点。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..models import PartResult, RedundancyGroupResult


def group_equivalent_lambda(lambdas: List[float], hours: float) -> Tuple[float, float]:
    """并联组：返回 (等效失效率, 组存活率)。

    lambdas: 组内各件的 λ（FIT）
    hours  : 求值时间点（通电小时）
    """
    if not lambdas:
        return 0.0, 1.0

    # 组内存活率：全坏才坏
    r_group = 1.0
    for lam in lambdas:
        r_i = math.exp(-(lam * hours) / 1e9) if hours > 0 else 1.0
        r_group *= (1.0 - r_i)
    r_group = 1.0 - r_group

    if hours <= 0:
        return 0.0, 1.0
    if r_group >= 1.0:
        return 0.0, 1.0
    if r_group <= 0.0:
        # 极端情况（数值下溢）：退化为串联相加，保证不会出现 inf
        return float(sum(lambdas)), 0.0

    # λ_eq = −ln(R_group) / hours，再换成 FIT 单位
    lambda_eq = (-math.log(r_group)) * 1e9 / hours
    return lambda_eq, r_group


@dataclass
class RbdModel:
    """整机可靠性框图的计算结果。"""

    series_lambda: float                          # 串联部分合计 λ（FIT）
    groups: List[RedundancyGroupResult]
    lambda_total: float                           # 整机 λ（串联 + 各组等效）
    lambda_total_without_redundancy: float        # 假设全串联时的 λ（用于展示冗余收益）


def build_rbd(
    parts: List[PartResult],
    redundancy_map: Dict[int, Optional[str]],
    hours: float,
) -> RbdModel:
    """组装整机模型。

    parts          : 每个零件的计算结果（含 λ_part）
    redundancy_map : {part_id: group_code 或 None}
    hours          : 评估时间点（目标年限折算的通电小时）
    """
    series_lambda = 0.0
    bucket: Dict[str, List[PartResult]] = {}

    for p in parts:
        grp = redundancy_map.get(p.part_id)
        if grp:
            bucket.setdefault(grp, []).append(p)
        else:
            series_lambda += p.lambda_part

    groups: List[RedundancyGroupResult] = []
    group_lambda_sum = 0.0
    for code, members in bucket.items():
        # 组内只有 1 个件时，"并联"退化为串联——这必须是显式行为，
        # 否则用户给单个件打了冗余标记，会误以为白赚了收益。
        if len(members) == 1:
            series_lambda += members[0].lambda_part
            continue
        lambdas = [m.lambda_part for m in members]
        lam_eq, r_g = group_equivalent_lambda(lambdas, hours)
        group_lambda_sum += lam_eq
        groups.append(
            RedundancyGroupResult(
                group=code,
                member_ids=[m.part_id for m in members],
                member_lambda_sum=float(sum(lambdas)),
                lambda_equiv=lam_eq,
                r_group=r_g,
            )
        )

    lambda_total = series_lambda + group_lambda_sum
    without_redundancy = series_lambda + sum(g.member_lambda_sum for g in groups)

    return RbdModel(
        series_lambda=series_lambda,
        groups=groups,
        lambda_total=lambda_total,
        lambda_total_without_redundancy=without_redundancy,
    )
