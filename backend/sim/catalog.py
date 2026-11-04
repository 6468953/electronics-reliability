"""
sim/catalog.py — 模拟 BOM 的元件目录

【这个模块做什么】
维护一份"看起来像真实 BOM"的元件目录：料号、真实写法的规格描述、典型用量、
以及演示需要的工作应力/额定值。模拟生成器按它铺数据。

【为什么不用随机字符串拼描述】
随机字符串造不出"高度相似的边界 case"（陶瓷/薄膜/铝电解都写 0.1uF 50V 0603），
也造不出"降额超限"（需要额定 25V 而工作 23V 这种有意的组合）。
所以目录是**手工设计**的，每个条目都对应一个演示意图；生成器只负责按规模复制变体。

【料号规则：不再自拟虚拟料号】
早期版本用 SIM-CAP-CER-100N50 这类自编号，问题很明显——导出报告给同事看时，
对方第一反应是"这是假的吧"，而且和真实物料系统对不上。现在按物料真实存在方式分三类：

  1. 通用电子元器件 → 填**真实厂商型号**（GRM188R71H104KA93D、RC0603FR-0710KL）。
     这些都是常见料，工程师一眼认得出，也方便自己去查规格书。
  2. 定制结构件/线束/包材 → 填**图号**（DWG-BRK-1042）。真实 BOM 里这类零件没有
     厂商型号，只有自家图纸编号，用图号才是对的。
  3. 标准紧固件/线材 → 填**国标号或线材规格**（GB/T818-M3×8-304、UL1007-AWG22-RED）。
     螺丝本来就没有"型号"，只有标准号 + 规格，这跟现实一致。

变体行也不再给料号加 "-01/-02" 后缀（那是伪造），而是换成同系列不同规格的真实型号。
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
# 常规条目：覆盖全部 18 个大类，描述按真实 BOM 写法（中英混排、单位不统一）
# ---------------------------------------------------------------------------
CATALOG: List[Dict[str, Any]] = [
    # --- 电容 ---
    _item("CAP_CER", "CC0603KRX7R9BB104", "CAP CER 0.1uF 50V X7R 0603 ±10%", 24,
          {"voltage": 3.3}, {"voltage": 50}, "C"),
    _item("CAP_CER", "GRM21BR61C106KE15L", "MLCC 10uF 16V X5R 0805", 6,
          {"voltage": 5.0}, {"voltage": 16}, "C"),
    _item("CAP_CER", "GRM1555C1H220JA01D", "CAP CER 22pF 50V C0G 0402", 4,
          {"voltage": 3.3}, {"voltage": 50}, "C"),
    _item("CAP_ALU", "EEUFR1V471", "CAP ALU 470uF 35V 105℃ 2000h φ10×12", 3,
          {"voltage": 24.0}, {"voltage": 35}, "C"),
    _item("CAP_ALU", "EEUFR1E102", "电解电容 1000uF/25V 低ESR 105度 5000h", 2,
          {"voltage": 23.0}, {"voltage": 25}, "C", tag="problem"),
    _item("CAP_FILM", "B32922C3474K000", "CAP FILM 0.47uF 630V CBB22 引脚间距15mm", 2,
          {"voltage": 300.0}, {"voltage": 630}, "C"),
    _item("CAP_TANT", "T491D107K016AT", "CAP TANT 100uF 16V 钽电容 CASE-D", 4,
          {"voltage": 8.0}, {"voltage": 16}, "C"),

    # --- 电阻 ---
    _item("RES_THICK", "RC0603FR-0710KL", "RES 10KΩ 1% 1/10W 0603 厚膜", 36,
          {"power": 0.02}, {"power": 0.1}, "R"),
    _item("RES_THICK", "RC0402JR-07100RL", "贴片电阻 100R 5% 0402", 18,
          {"power": 0.01}, {"power": 0.0625}, "R"),
    _item("RES_METAL_FILM", "MFR-25FBF52-22K", "RES METAL FILM 22KΩ 1% 1/4W 轴向", 4,
          {"power": 0.05}, {"power": 0.25}, "R"),
    _item("RES_WIREWOUND", "RX21-5W-10R", "线绕电阻 10Ω 5W 水泥封装", 2,
          {"power": 2.0}, {"power": 5.0}, "R"),
    _item("RES_POT", "3296W-1-103LF", "POT 10KΩ 多圈精密可调 3296W", 2,
          {"power": 0.1}, {"power": 0.5}, "RP"),

    # --- 电感 ---
    _item("IND_CHIP", "LQM18NN4R7K00D", "IND 4.7uH 0603 贴片电感", 6, {}, {}, "L"),
    _item("IND_POWER", "SRR6045-100M", "IND PWR 10uH 3A 屏蔽 6×6×4.5", 2,
          {"current": 1.5}, {"current": 3.0}, "L"),
    _item("IND_COMMON", "UU10.5-103", "CMC 10mH 2A 共模电感 双绕组", 2,
          {"current": 1.2}, {"current": 2.0}, "L"),

    # --- 二极管 ---
    _item("DIO_RECT", "1N4007", "DIO RECT 1N4007 1A 1000V DO-41 整流", 4,
          {"current": 0.6}, {"current": 1.0}, "D"),
    _item("DIO_SBD", "SS34", "DIO SBD SS34 3A 40V SMA 肖特基", 6,
          {"current": 2.4}, {"current": 3.0}, "D"),
    _item("DIO_ZENER", "BZT52C5V1-7-F", "DIO ZENER 5.1V 0.5W SOD-123 稳压管", 3,
          {"power": 0.2}, {"power": 0.5}, "D"),
    _item("DIO_TVS", "SMBJ12A", "DIO TVS SMBJ12A 600W 钳位19.9V", 4, {}, {}, "D"),

    # --- 晶体管 ---
    _item("TRA_BJT", "MMBT3904-7-F", "TRA NPN MMBT3904 SOT-23 hFE 100-300", 8,
          {"power": 0.1}, {"power": 0.35}, "Q"),
    _item("TRA_MOSFET", "SI2302CDS-T1-GE3", "TRA NMOS SI2302 SOT-23 20V 2.5A Rds(on)=60mΩ", 6,
          {"voltage": 12.0, "power": 0.4}, {"voltage": 20.0, "power": 1.25}, "Q"),
    _item("TRA_IGBT", "IKW20N60T", "IGBT 600V 20A TO-247", 2,
          {"voltage": 400.0, "power": 15.0}, {"voltage": 600.0, "power": 40.0}, "Q"),

    # --- IC ---
    _item("IC_ANALOG", "LM358DR", "IC OPAMP LM358 SOIC-8 双运放", 3,
          {"voltage": 12.0}, {"voltage": 32.0}, "U"),
    _item("IC_DIGITAL", "STM32F103C8T6", "IC MCU STM32F103C8T6 LQFP-48 72MHz", 1,
          {"voltage": 3.3}, {"voltage": 3.6}, "U"),
    _item("IC_MEMORY", "W25Q64JVSSIQ", "IC FLASH W25Q64 64Mbit SOP-8 SPI", 1,
          {"voltage": 3.3}, {"voltage": 3.6}, "U"),
    _item("IC_POWER", "AMS1117-3.3", "IC LDO AMS1117-3.3 SOT-223 800mA", 2,
          {"voltage": 5.0, "power": 0.6}, {"voltage": 15.0, "power": 1.2}, "U"),
    _item("IC_OPTO", "PC817X1NSZ0F", "IC OPTO PC817 DIP-4 CTR 50-600% 光耦", 2,
          {"current": 0.01}, {"current": 0.05}, "U"),

    # --- 连接器 ---
    _item("CONN_BOARD", "PZ254V-2-10P", "CONN BTB 2×10P 2.54mm 排针排母", 1, {}, {}, "J"),
    _item("CONN_WIRE", "XH2.54-4AW", "CONN XH2.54 4P 线对板 卧式", 2,
          {"current": 1.5}, {"current": 3.0}, "J"),
    _item("CONN_TERMINAL", "KF301-2P-5.08", "TERMINAL KF301-2P 5.08mm 接线端子", 2,
          {"current": 4.0}, {"current": 10.0}, "J"),

    # --- 晶振 ---
    _item("XTAL", "X49SM8MSD11A", "XTAL 8MHz 20ppm 负载电容12pF HC-49S 无源晶振", 1, {}, {}, "Y"),
    _item("OSC", "ASDMB-25.000MHZ-LC-T", "OSC 25MHz 3.3V ±25ppm 有源晶振 3225", 1,
          {"voltage": 3.3}, {"voltage": 3.6}, "Y"),

    # --- 保险丝 / 继电器 / 开关 ---
    _item("FUSE", "T2AL250V", "FUSE 2A 250V 慢断 5×20mm 保险丝", 1,
          {"current": 1.4}, {"current": 2.0}, "F"),
    _item("RELAY", "G5LE-1-DC5", "RELAY 5V 10A 1常开 电气寿命10万次", 2,
          {"current": 4.0, "daily_ops": 60}, {"current": 10.0}, "K", tag="problem"),
    _item("SWITCH", "TS-1088-6X6X5", "SWITCH 轻触 6×6×5mm 动作力160gf 寿命10万次", 3,
          {"daily_ops": 30}, {}, "SW"),

    # --- LED ---
    _item("LED", "LTST-C171KRKT", "LED 0805 红光 20mA Vf=2.0V", 6,
          {"current": 0.010}, {"current": 0.02}, "LED"),
    _item("LED", "LXW8-PW30", "照明LED 1W 3000K L70>25000h", 4,
          {"current": 0.3}, {"current": 0.35}, "LED", tag="problem"),

    # --- 模组 ---
    _item("MODULE_POWER", "IRM-10-5", "PWR MODULE AC-DC 5V 10W 隔离 电源模块", 1,
          {"power": 9.5}, {"power": 10.0}, "PS", tag="problem"),
    _item("MODULE_RF", "ESP-WROOM-02D", "RF MODULE WiFi 2.4G 802.11b/g/n 板载天线", 1,
          {"voltage": 3.3}, {"voltage": 3.6}, "U"),

    # --- 机电件 ---
    _item("FAN", "GM0504PEV1-8", "FAN 4010 5V 0.1A 6000RPM L10=30000h@40℃", 1, {}, {}, "B", tag="problem"),
    _item("PCB", "DWG-PCB-4L-001", "PCB FR-4 4层 1.6mm 沉金 无铅 主板", 1, {}, {}, "PCB"),
    _item("SOLDER", "SAC305-0.8MM", "SAC305 无铅焊锡丝 0.8mm 焊点 320 点", 320, {}, {}, "S"),

    # --- 结构五金 / 线缆 / 辅料 / 包装（标准未覆盖，见 params 里的 is_standard=false）---
    _item("MECH_ENCLOSURE", "DWG-ENC-2081", "ABS 注塑外壳 黑色 阻燃 V0 含前后面板", 1, {}, {}, "X"),
    _item("CABLE_HARNESS", "DWG-WH-3015", "XH2.54 4P 端子线 长200mm 双头 已压接", 2,
          {"daily_ops": 0}, {}, "W"),
    _item("CABLE_WIRE", "UL1007-AWG22-RED", "UL1007 AWG22 红色 电源线 105℃", 4, {}, {}, "W"),
    _item("THERMAL_PAD", "TG-A1250-1.5", "导热垫 1.5mm 30×30 双面自粘 1.5W/m·K", 2, {}, {}, "X"),
    _item("PKG_BOX", "DWG-PKG-5001", "彩盒 250×180×80 单瓦楞 含珍珠棉内衬", 1, {}, {}, "X"),
]


# ---------------------------------------------------------------------------
# 边界 case：演示三级分流。这 12 条是"必须能被看见"的，不随规模裁掉。
# ---------------------------------------------------------------------------
BOUNDARY_CASES: List[Dict[str, Any]] = [
    # 高度相似、必须分开的三兄弟（同一容值耐压，介质不同）
    _item("", "GRM188R71H104KA93D", "CAP CER 0.1uF 50V X7R 0603", 10, {}, {}, "C"),
    _item("", "B32529C1104K289", "CAP FILM 0.1uF 50V CBB22", 2, {}, {}, "C"),
    _item("", "EEUFR1H101", "CAP ALU 0.1uF 50V 105℃ 2000h", 2, {}, {}, "C"),
    # 部分相似：缺介质信息 → 应进人工确认
    _item("", "CC0805ZRY5V9BB104", "电容 0.1uF 50V 0603", 8, {}, {}, "C"),
    _item("", "RC0805FR-0710KL", "电阻 10K", 4, {}, {}, "R"),
    # 非电子件：以前归不了类，现在应落到结构件/紧固件
    _item("", "DWG-BRK-1042", "定制五金支架 SUS304 折弯件 t2.0", 2, {}, {}, "X"),
    _item("", "GB/T818-M3×8-304", "M3×8 十字圆头螺丝 不锈钢", 12, {}, {}, "X"),
    # 真正无法识别的：整条描述里没有任何品类信息，只能人工指定。
    # 保留这一条是为了让"未识别"这条分支在演示里始终有样本可看。
    _item("", "DWG-TC-2024", "特殊定制件 图纸见附件", 1, {}, {}, "X"),
    # 缩写/口语化：应能自动归类
    _item("", "RC0603FR-0710KL", "贴片电阻 10K 1% 0603", 6, {}, {}, "R"),
    # 张冠李戴陷阱：说的是电解，实际是固态高分子 → 应进人工确认
    _item("", "16SEPF680M", "电解电容 1000uF 25V 固态高分子", 2, {}, {}, "C"),
    # 描述过短
    _item("", "T3AL250V", "保险管 3A", 1, {}, {}, "F"),
    # 线束与导线最容易混：一条带端子压接，一条是裸线
    _item("", "DWG-WH-3021", "线束 4P 压接端子 长150mm", 2, {}, {}, "W"),
    _item("", "UL1015-AWG18-BLK", "导线 AWG18 黑色 耐温105℃", 6, {}, {}, "W"),
]


REF_LETTER = {"R": "R", "C": "C", "D": "D", "Q": "Q", "U": "U", "J": "J", "L": "L",
              "Y": "Y", "F": "F", "K": "K", "SW": "SW", "LED": "LED", "PS": "PS",
              "B": "B", "S": "S", "X": "X", "RP": "RP", "PCB": "PCB", "W": "W"}
