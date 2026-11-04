"""
sim/catalog.py — 模拟 BOM 的元件目录

【这个模块做什么】
维护一份"看起来像真实 BOM"的元件目录：自拟料号、真实写法的规格描述、典型用量、
以及演示需要的工作应力/额定值。模拟生成器按它铺数据。

【为什么不用随机字符串拼描述】
随机字符串造不出"高度相似的边界 case"（陶瓷/薄膜/铝电解都写 0.1uF 50V 0603），
也造不出"降额超限"（需要额定 25V 而工作 23V 这种有意的组合）。
所以目录是**手工设计**的，每个条目都对应一个演示意图；生成器只负责按规模复制变体。

【料号命名规则】
    SIM-<大类>-<子类>-<规格>    例：SIM-CAP-ALU-1000U25
前缀 SIM 明确表示"模拟数据"，避免与任何真实厂商料号混淆。
"""

from __future__ import annotations

from typing import Any, Dict, List


def _item(cat, pn, desc, qty, stress=None, rated=None, ref="", tag="") -> Dict[str, Any]:
    return {
        "category": cat,
        "part_number": pn,
        "description": desc,
        "qty": qty,
        "stress": stress or {},
        "rated": rated or {},
        "ref_prefix": ref,
        "tag": tag,   # normal / boundary / problem，用于生成器挑选用途
    }


# ---------------------------------------------------------------------------
# 常规条目：覆盖全部 14 个大类，描述按真实 BOM 写法（中英混排、单位不统一）
# ---------------------------------------------------------------------------
CATALOG: List[Dict[str, Any]] = [
    # --- 电容 ---
    _item("CAP_CER", "SIM-CAP-CER-100N50", "CAP CER 0.1uF 50V X7R 0603 ±10%", 24,
          {"voltage": 3.3}, {"voltage": 50}, "C"),
    _item("CAP_CER", "SIM-CAP-CER-10U16", "MLCC 10uF 16V X5R 0805", 6,
          {"voltage": 5.0}, {"voltage": 16}, "C"),
    _item("CAP_CER", "SIM-CAP-CER-22P50", "CAP CER 22pF 50V C0G 0402", 4,
          {"voltage": 3.3}, {"voltage": 50}, "C"),
    _item("CAP_ALU", "SIM-CAP-ALU-470U35", "CAP ALU 470uF 35V 105℃ 2000h φ10×12", 3,
          {"voltage": 24.0}, {"voltage": 35}, "C"),
    _item("CAP_ALU", "SIM-CAP-ALU-1000U25", "电解电容 1000uF/25V 低ESR 105度 5000h", 2,
          {"voltage": 23.0}, {"voltage": 25}, "C", tag="problem"),
    _item("CAP_FILM", "SIM-CAP-FILM-470N630", "CAP FILM 0.47uF 630V CBB22 引脚间距15mm", 2,
          {"voltage": 300.0}, {"voltage": 630}, "C"),
    _item("CAP_TANT", "SIM-CAP-TANT-100U16", "CAP TANT 100uF 16V 钽电容 CASE-D", 4,
          {"voltage": 8.0}, {"voltage": 16}, "C"),

    # --- 电阻 ---
    _item("RES_THICK", "SIM-RES-10K-0603", "RES 10KΩ 1% 1/10W 0603 厚膜", 36,
          {"power": 0.02}, {"power": 0.1}, "R"),
    _item("RES_THICK", "SIM-RES-100R-0402", "贴片电阻 100R 5% 0402", 18,
          {"power": 0.01}, {"power": 0.0625}, "R"),
    _item("RES_METAL_FILM", "SIM-RES-MF-22K", "RES METAL FILM 22KΩ 1% 1/4W 轴向", 4,
          {"power": 0.05}, {"power": 0.25}, "R"),
    _item("RES_WIREWOUND", "SIM-RES-WW-10R5W", "线绕电阻 10Ω 5W 水泥封装", 2,
          {"power": 2.0}, {"power": 5.0}, "R"),
    _item("RES_POT", "SIM-RES-POT-10K", "POT 10KΩ 多圈精密可调 3296W", 2,
          {"power": 0.1}, {"power": 0.5}, "RP"),

    # --- 电感 ---
    _item("IND_CHIP", "SIM-IND-CHIP-4U7", "IND 4.7uH 0603 贴片电感", 6, {}, {}, "L"),
    _item("IND_POWER", "SIM-IND-PWR-10U3A", "IND PWR 10uH 3A 屏蔽 6×6×4.5", 2,
          {"current": 1.5}, {"current": 3.0}, "L"),
    _item("IND_COMMON", "SIM-IND-CMC-10M", "CMC 10mH 2A 共模电感 双绕组", 2,
          {"current": 1.2}, {"current": 2.0}, "L"),

    # --- 二极管 ---
    _item("DIO_RECT", "SIM-DIO-1N4007", "DIO RECT 1N4007 1A 1000V DO-41 整流", 4,
          {"current": 0.6}, {"current": 1.0}, "D"),
    _item("DIO_SBD", "SIM-DIO-SS34", "DIO SBD SS34 3A 40V SMA 肖特基", 6,
          {"current": 2.4}, {"current": 3.0}, "D"),
    _item("DIO_ZENER", "SIM-DIO-BZT52-5V1", "DIO ZENER 5.1V 0.5W SOD-123 稳压管", 3,
          {"power": 0.2}, {"power": 0.5}, "D"),
    _item("DIO_TVS", "SIM-DIO-SMBJ12A", "DIO TVS SMBJ12A 600W 钳位19.9V", 4, {}, {}, "D"),

    # --- 晶体管 ---
    _item("TRA_BJT", "SIM-TRA-MMBT3904", "TRA NPN MMBT3904 SOT-23 hFE 100-300", 8,
          {"power": 0.1}, {"power": 0.35}, "Q"),
    _item("TRA_MOSFET", "SIM-TRA-SI2302", "TRA NMOS SI2302 SOT-23 20V 2.5A Rds(on)=60mΩ", 6,
          {"voltage": 12.0, "power": 0.4}, {"voltage": 20.0, "power": 1.25}, "Q"),
    _item("TRA_IGBT", "SIM-TRA-IGBT-600V20A", "IGBT 600V 20A TO-247", 2,
          {"voltage": 400.0, "power": 15.0}, {"voltage": 600.0, "power": 40.0}, "Q"),

    # --- IC ---
    _item("IC_ANALOG", "SIM-IC-LM358", "IC OPAMP LM358 SOIC-8 双运放", 3,
          {"voltage": 12.0}, {"voltage": 32.0}, "U"),
    _item("IC_DIGITAL", "SIM-IC-STM32F103", "IC MCU STM32F103C8T6 LQFP-48 72MHz", 1,
          {"voltage": 3.3}, {"voltage": 3.6}, "U"),
    _item("IC_MEMORY", "SIM-IC-W25Q64", "IC FLASH W25Q64 64Mbit SOP-8 SPI", 1,
          {"voltage": 3.3}, {"voltage": 3.6}, "U"),
    _item("IC_POWER", "SIM-IC-AMS1117", "IC LDO AMS1117-3.3 SOT-223 800mA", 2,
          {"voltage": 5.0, "power": 0.6}, {"voltage": 15.0, "power": 1.2}, "U"),
    _item("IC_OPTO", "SIM-IC-PC817", "IC OPTO PC817 DIP-4 CTR 50-600% 光耦", 2,
          {"current": 0.01}, {"current": 0.05}, "U"),

    # --- 连接器 ---
    _item("CONN_BOARD", "SIM-CONN-BTB-2X10", "CONN BTB 2×10P 2.54mm 排针排母", 1, {}, {}, "J"),
    _item("CONN_WIRE", "SIM-CONN-XH4P", "CONN XH2.54 4P 线对板 卧式", 2,
          {"current": 1.5}, {"current": 3.0}, "J"),
    _item("CONN_TERMINAL", "SIM-CONN-KF301", "TERMINAL KF301-2P 5.08mm 接线端子", 2,
          {"current": 4.0}, {"current": 10.0}, "J"),

    # --- 晶振 ---
    _item("XTAL", "SIM-XTAL-8M", "XTAL 8MHz 20ppm 负载电容12pF HC-49S 无源晶振", 1, {}, {}, "Y"),
    _item("OSC", "SIM-OSC-25M", "OSC 25MHz 3.3V ±25ppm 有源晶振 3225", 1,
          {"voltage": 3.3}, {"voltage": 3.6}, "Y"),

    # --- 保险丝 / 继电器 / 开关 ---
    _item("FUSE", "SIM-FUSE-2A", "FUSE 2A 250V 慢断 5×20mm 保险丝", 1,
          {"current": 1.4}, {"current": 2.0}, "F"),
    _item("RELAY", "SIM-RELAY-5V10A", "RELAY 5V 10A 1常开 电气寿命10万次", 2,
          {"current": 4.0, "daily_ops": 60}, {"current": 10.0}, "K", tag="problem"),
    _item("SWITCH", "SIM-SW-TACT-6X6", "SWITCH 轻触 6×6×5mm 动作力160gf 寿命10万次", 3,
          {"daily_ops": 30}, {}, "SW"),

    # --- LED ---
    _item("LED", "SIM-LED-0805-R", "LED 0805 红光 20mA Vf=2.0V", 6,
          {"current": 0.010}, {"current": 0.02}, "LED"),
    _item("LED", "SIM-LED-1W-3000K", "照明LED 1W 3000K L70>25000h", 4,
          {"current": 0.3}, {"current": 0.35}, "LED", tag="problem"),

    # --- 模组 ---
    _item("MODULE_POWER", "SIM-PWR-ACDC-5V10W", "PWR MODULE AC-DC 5V 10W 隔离 电源模块", 1,
          {"power": 9.5}, {"power": 10.0}, "PS", tag="problem"),
    _item("MODULE_RF", "SIM-RF-WIFI-2G4", "RF MODULE WiFi 2.4G 802.11b/g/n 板载天线", 1,
          {"voltage": 3.3}, {"voltage": 3.6}, "U"),

    # --- 机电件 ---
    _item("FAN", "SIM-FAN-4010-5V", "FAN 4010 5V 0.1A 6000RPM L10=30000h@40℃", 1, {}, {}, "B", tag="problem"),
    _item("PCB", "SIM-PCB-4L", "PCB FR-4 4层 1.6mm 沉金 无铅", 1, {}, {}, "PCB"),
    _item("SOLDER", "SIM-SOLDER-SAC305", "SOLDER 焊点 无铅 SAC305", 320, {}, {}, "S"),
]


# ---------------------------------------------------------------------------
# 边界 case：演示三级分流。这 10 条是"必须能被看见"的，不随规模裁掉。
# ---------------------------------------------------------------------------
BOUNDARY_CASES: List[Dict[str, Any]] = [
    # 高度相似、必须分开的三兄弟（同一容值耐压，介质不同）
    _item("", "SIM-CASE-001", "CAP CER 0.1uF 50V X7R 0603", 10, {}, {}, "C"),
    _item("", "SIM-CASE-002", "CAP FILM 0.1uF 50V CBB22", 2, {}, {}, "C"),
    _item("", "SIM-CASE-003", "CAP ALU 0.1uF 50V 105℃ 2000h", 2, {}, {}, "C"),
    # 部分相似：缺介质信息 → 应进人工确认
    _item("", "SIM-CASE-004", "电容 0.1uF 50V 0603", 8, {}, {}, "C"),
    _item("", "SIM-CASE-005", "电阻 10K", 4, {}, {}, "R"),
    # 完全不匹配：不是电子元件
    _item("", "SIM-CASE-006", "定制五金支架 SUS304 折弯件", 2, {}, {}, "X"),
    _item("", "SIM-CASE-007", "M3×8 十字圆头螺丝 不锈钢", 12, {}, {}, "X"),
    # 缩写/口语化：应能自动归类
    _item("", "SIM-CASE-008", "贴片电阻 10K 1% 0603", 6, {}, {}, "R"),
    # 张冠李戴陷阱：说的是电解，实际是固态高分子 → 应进人工确认
    _item("", "SIM-CASE-009", "电解电容 1000uF 25V 固态高分子", 2, {}, {}, "C"),
    # 描述过短
    _item("", "SIM-CASE-010", "保险管 3A", 1, {}, {}, "F"),
]


REF_LETTER = {"R": "R", "C": "C", "D": "D", "Q": "Q", "U": "U", "J": "J", "L": "L",
              "Y": "Y", "F": "F", "K": "K", "SW": "SW", "LED": "LED", "PS": "PS",
              "B": "B", "S": "S", "X": "X", "RP": "RP", "PCB": "PCB"}
