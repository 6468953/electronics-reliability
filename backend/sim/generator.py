"""
sim/generator.py — 模拟 BOM 生成器

【这个模块做什么】
按指定规模（几十 ~ 上千条）造一份"像真的" BOM，并保证三件演示必需的事：
  1. 覆盖全部元件大类（否则分类统计看板是一张空图）；
  2. 必含边界 case（高度相似 / 部分相似 / 完全不匹配），让三级分流都能被看到；
  3. 必含"问题零件"（降额超限、磨损最短、动作次数爆炸），让预警功能有东西可报。

【在整条流程中的位置】
    页面「一键生成演示 BOM」 → 本模块 → 行数据 → 与上传 BOM 走同一条解析/入库路径

【为什么模拟数据要"故意设计"而不是纯随机】
纯随机的描述会让所有算法都"看起来能用"：随机字符串与任何类目都不相似，于是全部落到
未识别，人也不会发现引擎有 bug。只有构造"陶瓷/薄膜/铝电解都写 0.1uF 50V"这种
高度相似的样本，才能真正验证分类引擎是不是在区分介质。
同理，只有造一只"额定 25V 却工作在 23V"的电容，降额检查才有意义。

【可复现性】
seed 固定时输出完全一致——报告与截图才能对得上，也方便回归测试。
"""

from __future__ import annotations

import random
from typing import Any, Dict, List

from .catalog import BOUNDARY_CASES, CATALOG, REF_LETTER

# 变体模板：规模放大时换成同系列、不同规格的**真实型号**，避免两种假象：
#   ① 同一句话重复 30 次；② 给真实料号拼 "-01/-02" 后缀伪造出新料号。
# 每项是 (料号, 描述) —— 描述变了额定值要跟着重算，见下面的 rated 处理。
VARIANTS: Dict[str, List[Dict[str, str]]] = {
    "CAP_CER": [
        {"pn": "CC0603KRX7R9BB103", "desc": "CAP CER 10nF 50V X7R 0603"},
        {"pn": "GRM21BR61A475KA73L", "desc": "MLCC 4.7uF 10V X5R 0805"},
        {"pn": "CL05B223KO5NNNC", "desc": "CAP CER 22nF 16V X7R 0402"},
        {"pn": "CC0402KRX7R7BB224", "desc": "CAP CER 100nF 16V X7R 0402"},
    ],
    "CAP_ALU": [
        {"pn": "EEUFR1H221", "desc": "CAP ALU 220uF 50V 105℃ 3000h φ8×12"},
        {"pn": "EEUFR1V331", "desc": "电解电容 330uF/35V 低ESR 105度"},
        {"pn": "EEUFR1J101", "desc": "CAP ALU 100uF 63V 105℃ 2000h φ10×16"},
    ],
    "RES_THICK": [
        {"pn": "RC0603FR-074K7L", "desc": "RES 4.7KΩ 1% 1/10W 0603"},
        {"pn": "RC0402FR-071KL", "desc": "贴片电阻 1K 1% 0402"},
        {"pn": "RC0805FR-0747KL", "desc": "RES 47KΩ 1% 1/8W 0805"},
        {"pn": "RC0603FR-07100KL", "desc": "贴片电阻 100K 1% 0603"},
        {"pn": "RC1206JR-072R2L", "desc": "RES 2.2Ω 5% 1/4W 1206"},
    ],
    "IND_CHIP": [
        {"pn": "LQM18NN100K00D", "desc": "IND 10uH 0805 贴片电感"},
        {"pn": "LQP03TN1N0B02D", "desc": "IND 1nH 0201 叠层电感"},
    ],
    "DIO_SBD": [
        {"pn": "SS14", "desc": "DIO SBD SS14 1A 40V SMA 肖特基"},
        {"pn": "SS54", "desc": "DIO SBD SS54 5A 40V SMC"},
    ],
    "DIO_RECT": [
        {"pn": "1N5408", "desc": "DIO RECT 1N5408 3A 1000V DO-201 整流"},
        {"pn": "1N4004", "desc": "DIO RECT 1N4004 1A 400V DO-41"},
    ],
    "TRA_BJT": [
        {"pn": "S8050", "desc": "TRA NPN S8050 SOT-23"},
        {"pn": "MMBT3906-7-F", "desc": "TRA PNP MMBT3906 SOT-23"},
    ],
    "TRA_MOSFET": [
        {"pn": "AO3400A", "desc": "TRA NMOS AO3400 SOT-23 30V 5.7A"},
        {"pn": "AO3401A", "desc": "TRA PMOS AO3401 SOT-23"},
    ],
    "IC_DIGITAL": [
        {"pn": "STM32F030C8T6", "desc": "IC MCU STM32F030C8T6 LQFP-48"},
        {"pn": "SN74HC595DR", "desc": "逻辑IC 74HC595 SOP-16"},
    ],
    "IC_POWER": [
        {"pn": "AMS1117-5.0", "desc": "IC LDO AMS1117-5.0 SOT-223"},
        {"pn": "MP1584EN", "desc": "IC DC-DC MP1584EN SOP-8 3A"},
    ],
    "LED": [
        {"pn": "LTST-C191KGKT", "desc": "LED 0603 绿光 20mA Vf=2.1V"},
        {"pn": "LTST-C171TBKT", "desc": "LED 0805 蓝光 20mA"},
    ],
    "FAN": [
        {"pn": "AFB0512HD", "desc": "FAN 5015 12V 0.12A L10=35000h@40℃"},
        {"pn": "GM0503PEV1-8", "desc": "FAN 3010 5V 0.08A L10=25000h@40℃"},
    ],
    "RELAY": [
        {"pn": "G5LE-1-DC12", "desc": "RELAY 12V 5A 1常开 电气寿命10万次"},
        {"pn": "G2R-2-DC24", "desc": "RELAY 24V 3A 2常开 电气寿命10万次"},
    ],
    "SWITCH": [
        {"pn": "TS-1088-6X6X6", "desc": "SWITCH 轻触 6×6×6mm 寿命10万次"},
        {"pn": "KCD1-101", "desc": "SWITCH 船型 KCD1 2档 6A"},
    ],
    "CONN_WIRE": [
        {"pn": "XH2.54-6AW", "desc": "CONN PH2.0 6P 线对板"},
        {"pn": "TYPE-C-16P-SMD", "desc": "CONN USB Type-C 16P 母座 贴片"},
    ],
    "MODULE_POWER": [
        {"pn": "IRM-20-12", "desc": "PWR MODULE AC-DC 12V 20W 隔离"},
        {"pn": "TSR-1-2450", "desc": "PWR MODULE DC-DC 24V转5V 1A"},
    ],
}

# 这些零件在真实 BOM 里通常只有一条（每板一片 / 工艺项），不做复制。
# 硬复制会出现"两块 PCB""两份焊膏"这种一眼假的组合。
UNIQUE_CATEGORIES = {"PCB", "SOLDER"}


def _ref_des(prefix: str, index: int) -> str:
    letter = REF_LETTER.get(prefix, prefix or "X")
    return f"{letter}{index}"


def generate(
    scale: int = 200,
    seed: int = 42,
    include_cases: bool = True,
    include_dirty: bool = False,
) -> List[Dict[str, Any]]:
    """生成 BOM 行列表。

    scale         : 目标行数（50 / 200 / 1000 常见）
    seed          : 随机种子，固定即复现
    include_cases : 是否注入边界 case（演示时必须为 True）
    include_dirty : 是否注入脏数据（重复料号、缺数量），用于演示校验告警
    """
    rng = random.Random(seed)
    rows: List[Dict[str, Any]] = []
    counters: Dict[str, int] = {}

    # ---- 1. 边界 case 优先铺在最前面，保证不会被规模裁掉 ----
    if include_cases:
        for item in BOUNDARY_CASES:
            prefix = item["ref_prefix"]
            counters[prefix] = counters.get(prefix, 0) + 1
            rows.append(
                {
                    "part_number": item["part_number"],
                    "description": item["description"],
                    "qty": item["qty"],
                    "ref_des": _ref_des(prefix, counters[prefix]),
                    "suggested_stress": item["stress"],
                    "suggested_rated": item["rated"],
                    "tag": "boundary",
                }
            )

    # ---- 2. 常规条目铺满规模 ----
    base = list(CATALOG)
    # 标为 problem 的条目（降额超限/磨损最短）只出现一次，不参与复制。
    # 理由：这些行是"故意设计的问题零件"，用来演示预警功能。如果把它们复制成
    # 十几个变体，违规清单就会从"4 条可逐条处理"变成"35 条面目相似的噪音"，
    # 用户反而看不出哪条是要动设计的问题行。
    replicable = [
        it
        for it in base
        if it.get("tag") != "problem" and it["category"] not in UNIQUE_CATEGORIES
    ]
    # 料号 -> 行下标。真实 BOM 里同一料号只占一行（用量合并），
    # 所以重复出现时累加 qty，而不是再插一行。
    pn_index: Dict[str, int] = {r["part_number"]: idx for idx, r in enumerate(rows)}
    i = 0
    guard = 0
    # 材料（真实型号）是有限的，凑不满 scale 时不能死循环：
    # 一轮 base + 12 轮变体足够把所有变体都铺出来，还没满就说明料号用完了。
    max_guard = (len(base) + len(replicable) * 12) * 2
    while len(rows) < scale and guard < max_guard:
        guard += 1
        if i < len(base):
            item = base[i]
            k = 0
        else:
            item = replicable[(i - len(base)) % len(replicable)]
            k = 1 + (i - len(base)) // len(replicable)
        prefix = item["ref_prefix"]

        if k == 0:
            desc = item["description"]
            pn = item["part_number"]
            qty = item["qty"]
            stress = dict(item["stress"])
            rated = dict(item["rated"])
            tag = item["tag"]
        else:
            tag = "normal"
        variants = VARIANTS.get(item["category"])
        # 每一轮都从"基准条目的用量"重新出发。
        # 【踩过的坑】这里曾经漏了这行，导致 qty 沿用了上一行的值
        # （比如上一条是 320 个焊点），变体电解电容就凭空变成 500 只，
        # 整机失效率被放大 20 倍、MTBF 从 60 万小时掉到 3.6 万小时。
        # 这类"变量跨迭代残留"的 bug 不会报错，只会让演示数据看起来荒谬。
        qty = item["qty"]
        if variants:
            v = variants[k % len(variants)]
            desc = v["desc"]
            pn = v["pn"]
            # 描述变了，额定值也要跟着变，否则降额检查会拿错额定值
            rated = dict(item["rated"])
            if "uF" in desc or "uF" in desc.upper():
                rated["voltage"] = _first_voltage(desc) or rated.get("voltage")
            # 工作应力按【基准条目的应力/额定比值】等比推到新额定值上。
            # 早期版本这里写死了 0.7 / 0.65 / 0.55，结果凭空造出三十多条"降额超限"：
            # 因为不同类目的规范上限不同（电阻功率上限 0.5、电感电流上限 0.6），
            # 统一按 0.7 推就必然有一批"违规"。保持基准比值，才能让"设计好的问题零件"
            # （比如 25V 电容工作在 23V）继续是唯一被标红的那几条。
            stress = dict(item["stress"])
            base_rated = item["rated"]
            for key in ("voltage", "current", "power"):
                if rated.get(key) and base_rated.get(key) and stress.get(key):
                    ratio = float(stress[key]) / float(base_rated[key])
                    stress[key] = round(float(rated[key]) * ratio, 4)
        else:
            # 没有变体模板的类目（如钽电容、晶振、端子）：描述与料号保持不变，
            # 只扰动用量。真实 BOM 里同一料号分多行写是常见现象，导入校验会提示
            # 「建议合并」但不阻断——这比给料号拼一个 "-02" 后缀诚实的多。
            desc = item["description"]
            pn = item["part_number"]
            qty = max(1, int(item["qty"] * rng.uniform(0.5, 1.2)))
            stress = dict(item["stress"])
            rated = dict(item["rated"])

        if k > 0:
            # 用量做小幅扰动，让"Top 短板"排序有真实感（不会永远同一个料号第一）
            qty = max(1, int(qty * rng.uniform(0.6, 1.6)))

        if pn in pn_index:
            # 这个料号已经在表里了：直接跳过，既不重复出行、也不累加用量。
            # 【为什么不能累加】早期试过"并到同一行、用量相加"，结果一块板上出现
            # 26 个 WiFi 模组、353 只电阻——用量被复制轮次无限放大，MTBF 直接从
            # 百万小时掉到 20 万小时。演示数据宁可少几行，也不能出现物理上不成立的用量。
            i += 1
            continue

        counters[prefix] = counters.get(prefix, 0) + 1
        rows.append(
            {
                "part_number": pn,
                "description": desc,
                "qty": qty,
                "ref_des": _ref_des(prefix, counters[prefix]),
                "suggested_stress": stress,
                "suggested_rated": rated,
                "tag": tag,
            }
        )
        pn_index[pn] = len(rows) - 1
        i += 1

    # ---- 3. 脏数据：校验功能的演示素材 ----
    if include_dirty and rows:
        rows.append(
            {
                "part_number": rows[0]["part_number"],
                "description": rows[0]["description"],
                "qty": 2,
                "ref_des": "C99",
                "suggested_stress": {},
                "suggested_rated": {},
                "tag": "dirty_dup",
            }
        )
        rows.append(
            {
                "part_number": "SIM-DIRTY-NOQTY",
                "description": "贴片电阻 220R 1% 0603",
                "qty": None,
                "ref_des": "R99",
                "suggested_stress": {},
                "suggested_rated": {},
                "tag": "dirty_noqty",
            }
        )

    for idx, r in enumerate(rows, start=1):
        r["line_no"] = idx
        r.pop("tag", None)

    return rows


def _first_voltage(desc: str):
    from core.parse_spec import normalize, parse_voltage

    return parse_voltage(normalize(desc))
