"""
core/reliability/survival.py — 存活率、MTBF 与时间折算

【这个模块做什么】
把"失效率"这个瞬时风险量，换算成用户能听懂的两个数：
  - MTBF（平均无故障时间）
  - R(t)（存活到 t 时刻的概率）

【在整条流程中的位置】
    λ_total(FIT) → mtbf_hours() → survival() → 判定 PASS/FAIL → 报告首页大字

【为什么需要它】
失效率是每秒每件产品坏掉的概率，量级 10^-8 /小时，人类无法直觉理解。
工程上统一用 MTBF 表达"平均多久坏一次"，用 R(t) 表达"用 N 年还剩多少台好的"。
但两者不能混：MTBF 是随机失效（指数分布）的口径，**不等于寿命**。

【核心公式与通俗解释】
1) MTBF = 1e9 / λ_FIT
   λ_FIT 的单位是"每 10^9 小时失效次数"，所以把它取倒数再乘 1e9 就是平均间隔小时数。
   例：整机 100 FIT → MTBF = 10,000,000 小时 ≈ 1141 年。

2) R(t) = exp(−t / MTBF)       （指数分布的无记忆性）
   例：MTBF = 100 万小时，工作 5 年（43800 小时）→ R = exp(−0.0438) ≈ 95.7%。
   **注意**：R(t) 才是"5 年存活率"的正确算法，不能用「5年 / MTBF」当失效率。

3) 时间折算
   设备不是 24 小时全年通电的，MTBF 与 R(t) 必须按实际通电小时算：
       t_通电 = 年限 × 8760 小时/年 × 通电占比（duty cycle）
   一台每天开 8 小时的设备，5 年只积累了 14600 小时，而不是 43800 小时。
   duty 还会影响失效率本身（不通电时不劣化），本系统采用"只在通电时间累积风险"的简化。
"""

from __future__ import annotations

import math

HOURS_PER_YEAR = 8760.0


def mtbf_from_fit(lambda_fit: float) -> float:
    """FIT → MTBF（小时）。λ 为 0 时返回无穷大（理想串联系统）。"""
    if lambda_fit <= 0:
        return float("inf")
    return 1e9 / lambda_fit


def fit_from_mtbf(mtbf_hours: float) -> float:
    """MTBF（小时）→ FIT。"""
    if mtbf_hours <= 0 or math.isinf(mtbf_hours):
        return 0.0
    return 1e9 / mtbf_hours


def operating_hours(target_years: float, duty_cycle: float) -> float:
    """目标年限 → 实际累积通电小时数。"""
    duty = max(0.0, min(1.0, float(duty_cycle)))
    return float(target_years) * HOURS_PER_YEAR * duty


def survival(lambda_fit: float, hours: float) -> float:
    """R(t) = exp(−λ × t)，λ 用 FIT 时需除以 1e9 转成 1/小时。"""
    if hours <= 0:
        return 1.0
    return math.exp(-(lambda_fit * hours) / 1e9)


def survival_at_years(lambda_fit: float, years: float, duty_cycle: float) -> float:
    return survival(lambda_fit, operating_hours(years, duty_cycle))


def hours_to_reach_survival(lambda_fit: float, target_r: float) -> float:
    """由目标存活率反推可支撑的通电小时数：t = −ln(R) / λ。"""
    if lambda_fit <= 0:
        return float("inf")
    r = max(1e-12, min(0.999999, target_r))
    return -math.log(r) * 1e9 / lambda_fit


def years_to_reach_survival(lambda_fit: float, target_r: float, duty_cycle: float) -> float:
    """由目标存活率反推年限（随机失效视角）。用于"整机结论 = min(随机, 磨损)"的比较。"""
    h = hours_to_reach_survival(lambda_fit, target_r)
    if math.isinf(h):
        return float("inf")
    denom = HOURS_PER_YEAR * max(1e-6, min(1.0, float(duty_cycle)))
    return h / denom


def format_mtbf(mtbf_hours: float) -> str:
    """人性化显示：小时 / 年，两者都给，避免"1141 年"这种反直觉数字被误解。"""
    if math.isinf(mtbf_hours):
        return "∞"
    if mtbf_hours >= HOURS_PER_YEAR:
        return f"{mtbf_hours:,.0f} h（约 {mtbf_hours / HOURS_PER_YEAR:,.1f} 年连续运行）"
    return f"{mtbf_hours:,.0f} h"
