"""
core/parse_spec.py — 从规格描述里解析额定参数

【这个模块做什么】
BOM 里的规格描述是"人写给同行看的"，不是结构化数据：
    "CAP ALU 1000uF 25V 105℃ 2000h φ10×20"
    "RELAY 5V 10A 1常开 电气寿命10万次"
    "FAN 4010 5V 0.1A 6000RPM L10=30000h@40℃"
本模块用规则（正则）+ 单位归一化，把这些数字抠出来，供降额检查与磨损寿命计算使用。

【在整条流程中的位置】
    bom_items.description → parse_spec() → rated{voltage, capacitance_uf, temp_max_c, life_h...}
                                              ↓
                                    降额检查（对比工作应力）/ 磨损寿命（代公式）

【为什么需要它，以及它的边界】
  - 需要的理由：如果让用户手填每个零件的额定电压/寿命，一千条 BOM 就要填一千次，
    没人会填。能自动解析 80% 的常见写法，剩下的标「缺数据」再人工补，才是可用的产品。
  - 边界：这是【启发式解析】，不是理解语义。像 "耐压50V/-55~105℃" 这类复合写法、
    或者中文混写 "耐压五十伏"，解析器会失败。失败时的正确行为是**明确标为缺数据**，
    而不是猜一个看起来合理的数——猜出来的数会静默污染整份报告。

【单位归一化规则（务必先做再匹配）】
  1. 全角转半角，µF/μF/uf → uF，pF/nF 保留（转成 uF 便于比较）
  2. 大写化后匹配，但保留原始文本用于报告展示
  3. "1/10W" 这类分数功率要单独处理，否则会解析成 "10W"
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# 电容换算到 uF 的倍率
CAP_MULT = {"PF": 1e-6, "NF": 1e-3, "UF": 1.0, "MF": 1000.0}

# 电流换算到 A 的倍率
CUR_MULT = {"UA": 1e-6, "MA": 1e-3, "A": 1.0}

_FULLWIDTH = str.maketrans("０１２３４５６７８９．／×", "0123456789./×")


def normalize(text: str) -> str:
    """把描述文本规整成便于正则匹配的形式。"""
    if not text:
        return ""
    s = str(text).translate(_FULLWIDTH)
    s = s.replace("μ", "u").replace("µ", "u").replace("Ω", "Ω")
    s = s.replace("℃", "°C").replace("°c", "°C")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _to_float(x: str) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_capacitance(s: str) -> Optional[float]:
    """解析容值，统一换算为 uF。例：0.1uF → 0.1；100nF → 0.1；22pF → 0.000022"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(uf|nf|pf|mf)\b", s, re.I)
    if not m:
        return None
    val = _to_float(m.group(1))
    unit = m.group(2).upper()
    if val is None:
        return None
    return round(val * CAP_MULT.get(unit, 1.0), 9)


def parse_voltage(s: str) -> Optional[float]:
    """解析电压（V）。跳过 "5VAC/220VAC" 这类写法中的 AC 尾巴，只取数字。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*v(?![a-z])", s, re.I)
    if not m:
        return None
    return _to_float(m.group(1))


def parse_power(s: str) -> Optional[float]:
    """解析功率（W）。先处理 "1/10W" 分数写法，再处理 "0.25W" / "5W"。"""
    m = re.search(r"1\s*/\s*(\d+)\s*w\b", s, re.I)
    if m:
        denom = _to_float(m.group(1))
        if denom:
            return round(1.0 / denom, 6)
    m = re.search(r"(\d+(?:\.\d+)?)\s*w\b", s, re.I)
    if m:
        return _to_float(m.group(1))
    return None


def parse_current(s: str) -> Optional[float]:
    """解析电流（A）。注意毫安与安培的区分：mA → 0.001A。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ua|ma|a)\b", s, re.I)
    if not m:
        return None
    val = _to_float(m.group(1))
    if val is None:
        return None
    return round(val * CUR_MULT.get(m.group(2).upper(), 1.0), 9)


def parse_temp_max(s: str) -> Optional[float]:
    """解析温度上限（°C）。

    认三种写法："105℃"、"105 °C"、"105度"。最后一种在国内 datasheet 与采购描述里很常见
    （"低ESR 105度"），漏掉它会让电解电容的额定温度永远读不到，磨损与降额都判"缺数据"。
    仍然要求数字是 2~3 位，避免把 "0603" 之类的封装号误当温度。
    """
    m = re.search(r"(-?\d{2,3})\s*(?:°\s*c|℃|度)", s, re.I)
    if m:
        val = _to_float(m.group(1))
        if val is not None and -60 <= val <= 200:
            return val
    return None


def parse_life_hours(s: str) -> Optional[float]:
    """解析额定寿命（小时）。例："2000h"、"10000小时"、"L10=30000h@40℃"。"""
    m = re.search(r"l10\s*[=＝:：]?\s*(\d{3,6})\s*(?:h|小时)", s, re.I)
    if m:
        return _to_float(m.group(1))
    m = re.search(r"l70\s*[>≥=＝:：]?\s*(\d{3,6})", s, re.I)
    if m:
        return _to_float(m.group(1))
    m = re.search(r"(\d{3,6})\s*(?:h|小时)\b", s, re.I)
    if m:
        val = _to_float(m.group(1))
        # 排除 "24h" 这种运行时长描述（<100h 不当额定寿命）
        if val and val >= 100:
            return val
    return None


def parse_ref_temp(s: str) -> Optional[float]:
    """解析寿命的参考温度，即 "L10=30000h@40℃" 里的 40。"""
    m = re.search(r"@\s*(-?\d{2,3})\s*°?\s*c", s, re.I)
    if m:
        return _to_float(m.group(1))
    return None


def parse_cycles(s: str) -> Optional[float]:
    """解析动作次数。支持 "10万次" / "5000 cycles" / "30次插拔"。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*万\s*次", s)
    if m:
        val = _to_float(m.group(1))
        return val * 10000 if val is not None else None
    m = re.search(r"(\d{1,7})\s*(?:cycles?|次)\b", s, re.I)
    if m:
        return _to_float(m.group(1))
    return None


def parse_spec(description: str) -> Dict[str, Any]:
    """一条描述 → 结构化额定参数（只返回解析到的键）。"""
    s = normalize(description)
    out: Dict[str, Any] = {}

    cap = parse_capacitance(s)
    if cap is not None:
        out["capacitance_uf"] = cap
    v = parse_voltage(s)
    if v is not None:
        out["voltage"] = v
    p = parse_power(s)
    if p is not None:
        out["power"] = p
    a = parse_current(s)
    if a is not None:
        out["current"] = a
    t = parse_temp_max(s)
    if t is not None:
        out["temp_max_c"] = t
    life = parse_life_hours(s)
    if life is not None:
        out["life_h"] = life
    rt = parse_ref_temp(s)
    if rt is not None:
        out["ref_temp_c"] = rt
    cyc = parse_cycles(s)
    if cyc is not None:
        out["cycles"] = cyc

    # 修正：@40℃ 这类写法是"寿命的参考温度"，不是"最高工作温度"。
    # 若两者被解析成同一个数，说明只出现了 @ 形式，此时不能把它当成额定上限——
    # 否则降额的温度余量判定会拿 40℃ 当额定上限，得出完全错误的结论。
    if "ref_temp_c" in out and out.get("temp_max_c") == out["ref_temp_c"]:
        out.pop("temp_max_c", None)

    return out


def merge_rated(
    stored: Optional[Dict[str, Any]], description: str
) -> tuple:
    """合并"人工补录/数据库里已存的额定值"与"从描述解析出的值"。

    优先级：已存值 > 描述解析值。返回 (merged, 每个字段的来源 dict)。

    为什么要区分来源：报告里必须能回答"这个 0.8 的降额系数是基于谁填的数算的"，
    否则出了问题无处追溯。
    """
    parsed = parse_spec(description)
    merged: Dict[str, Any] = {}
    sources: Dict[str, str] = {}

    for k, v in parsed.items():
        merged[k] = v
        sources[k] = "parsed"

    if stored:
        for k, v in stored.items():
            if k.startswith("_"):
                continue
            if v is None or v == "":
                continue
            if isinstance(v, str):
                try:
                    v = float(v)
                except ValueError:
                    continue
            merged[k] = v
            sources[k] = "manual"

    return merged, sources
