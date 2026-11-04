"""
core/classify/normalize.py — 规格描述归一化

【这个模块做什么】
把 BOM 里五花八门的规格描述，规整成"可比较"的标准形式，再切成分词序列。

输入示例（真实 BOM 里都出现过）：
    "CAP CER 0.1UF 50V X7R 0603"
    "贴片陶瓷电容 100nF/50V ±10% 0603 封装"
    "MLCC 0.1uF 50V X7R 0603 ROHS"
这三个是同一个东西，但字符串相似度很低。归一化就是消除这些"写法差异"。

【在整条流程中的位置】
    description → normalize → tokens/特征 → similarity 打分 → engine 分流

【归一化做的五件事，以及为什么每一件都必要】
1. 全角→半角、大写化      ：中文 BOM 里全角字符极常见（０.１ｕＦ），不转就匹配不上
2. 单位统一（μF/uF/uf）    ：同一个单位三种写法；容值单位还要换算成 uF 才能比较大小
3. 去噪声词                 ："贴片""原装""环保""ROHS""无铅" 对"这是什么元件"没有信息量，
                              留着会让所有类目的相似度一起抬高，反而稀释了区别性特征
4. 数字+单位切分             ：jieba 会把 "0.1uF" 切成 "0.1" + "uf"，也可能切成整体，
                              统一成 <NUM> + 单位 token，避免容值具体数值干扰类别判断
5. 领域词典               ：jieba 默认词典不认识 "X7R""NP0""低ESR""L10"，
                              不加词典会把它们切碎，等于丢掉最关键的判别特征
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence

try:
    import jieba
except ImportError:  # 允许在没有 jieba 的环境下退化运行（测试里会跳过相关用例）
    jieba = None

# 全角 → 半角
_FULLWIDTH_MAP = {ord(c): ord(h) for c, h in zip("０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ．／（）％", "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz./()%")}

# 噪声词：对"这是什么元件"没有判别力，但会污染相似度。
# 注意：这里刻意【不】去掉"贴片"以外的封装词（0402/0603），因为封装有时能区分器件类型
# （比如 0402 常见于电阻电容，TO-220 只可能是功率器件）。
NOISE_WORDS = [
    "原装", "正品", "进口", "国产", "rohs", "无铅", "环保", "新料", "现货",
    "封装", "规格", "型号", "品牌", "厂家", "替代", "兼容", "工业级", "商用级",
    "±1%", "±5%", "±10%", "±0.1%", "精度",
]

# 领域词典：这些词必须整体成词，否则关键特征会被切碎
DOMAIN_WORDS = [
    "铝电解", "电解电容", "陶瓷电容", "薄膜电容", "钽电容", "贴片电容", "固态电容",
    "贴片电阻", "金属膜", "线绕", "水泥电阻", "精密电阻", "电位器", "可调电阻",
    "贴片电感", "功率电感", "共模电感", "叠层电感", "扼流圈",
    "整流", "肖特基", "稳压管", "稳压二极管", "齐纳", "瞬态抑制", "钳位",
    "三极管", "场效应", "绝缘栅双极",
    "运放", "运算放大器", "比较器", "基准源", "电源管理", "稳压器", "光耦", "光电隔离",
    "板对板", "线对板", "排针", "排母", "端子", "接线柱", "连接器",
    "无源晶振", "有源晶振", "温补晶振", "晶振",
    "保险丝", "熔断器", "自恢复", "继电器", "固态继电器", "触点", "线圈", "电气寿命",
    "轻触开关", "按键", "拨动开关", "船型开关", "动作力",
    "发光二极管", "光通维持", "色温", "光衰",
    "电源模块", "隔离电源", "射频", "模组", "天线",
    "风扇", "散热风机", "轴流", "轴承", "滚珠", "含油",
    "线路板", "印制板", "沉金", "喷锡", "焊点",
    "低esr", "高容值", "直流偏压", "饱和电流", "温漂", "正向压降", "反向恢复",
    "额定寿命", "环境温度", "工作温度", "降额",
    "x7r", "x5r", "c0g", "np0", "y5v", "mlcc", "sbd", "tvs", "esd", "igbt", "mosfet",
    "bjt", "ldo", "dcdc", "pmic", "tcxo", "ssr", "ptc", "btb",
]

_domain_dict_loaded = False


def ensure_domain_dict() -> None:
    """把领域词加进 jieba 词典（只做一次）。"""
    global _domain_dict_loaded
    if _domain_dict_loaded or jieba is None:
        return
    for w in DOMAIN_WORDS:
        jieba.add_word(w, freq=20000)
    _domain_dict_loaded = True


_NUM_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(uf|nf|pf|mh|uh|nh|kω|mω|ω|k|m|v|a|w|hz|khz|mhz|%|mm|℃|°c)")


def normalize_text(text: str, drop_noise: bool = True) -> str:
    """规整文本：全半角、大小写、单位写法、去噪声。"""
    if not text:
        return ""
    s = str(text).translate(_FULLWIDTH_MAP)
    s = s.replace("μ", "u").replace("µ", "u").replace("Ω", "ω")
    s = s.replace("℃", "°c")
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()

    if drop_noise:
        for w in NOISE_WORDS:
            s = s.replace(w, " ")

    # 在数字与单位之间补空格，避免 "10kω" 被当成一个词，也便于特征抽取
    s = _NUM_UNIT.sub(lambda m: f"{m.group(1)} {m.group(2)}", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokenize(text: str) -> List[str]:
    """分词。没有 jieba 时退化为"按空白 + 单字"的粗切（保证不崩）。"""
    if not text:
        return []
    ensure_domain_dict()
    if jieba is None:
        return [t for t in re.split(r"[\s,/;()]+", text) if t]
    return [t.strip() for t in jieba.lcut(text) if t.strip()]


def tokens_of(text: str) -> List[str]:
    """归一化 + 分词，一次到位。"""
    return tokenize(normalize_text(text))


STOP_TOKENS = {"的", "和", "与", "或", "及", " ", "/", "-", "(", ")", "，", ",", "。", "±", "×"}


def clean_tokens(tokens: Sequence[str]) -> List[str]:
    return [t for t in tokens if t not in STOP_TOKENS and len(t) > 0]


# ---------------------------------------------------------------------------
# 特征抽取：把描述里的"关键判别信息"取出来，既用于打分，也用于界面展示
# ---------------------------------------------------------------------------

DIELECTRIC = {"x7r", "x5r", "c0g", "np0", "y5v", "z5u"}
PACKAGES = re.compile(r"\b(0201|0402|0603|0805|1206|1210|1812|2010|2512|sot-23|sot23|sot-223|to-92|to-220|to-247|do-41|do-214|sma|smb|smc|sod-123|sod-323|dip-4|dip-8|soic-8|sop-8|qfn|lfp|hc-49)\b")


def extract_features(description: str) -> Dict[str, object]:
    """抽取结构化特征。返回值同时用于：打分加权、界面展示"为什么这么判"。"""
    s = normalize_text(description)
    feats: Dict[str, object] = {}

    caps = re.findall(r"(\d+(?:\.\d+)?)\s*(uf|nf|pf)\b", s)
    if caps:
        feats["capacitance"] = [f"{v}{u}" for v, u in caps]

    ohms = re.findall(r"(\d+(?:\.\d+)?)\s*(kω|mω|ω)\b", s)
    if ohms:
        feats["resistance"] = [f"{v}{u}" for v, u in ohms]

    henries = re.findall(r"(\d+(?:\.\d+)?)\s*(mh|uh|nh)\b", s)
    if henries:
        feats["inductance"] = [f"{v}{u}" for v, u in henries]

    volts = re.findall(r"(\d+(?:\.\d+)?)\s*v\b", s)
    if volts:
        feats["voltage"] = [f"{v}v" for v in volts]

    temp = re.findall(r"(-?\d{2,3})\s*°?\s*c\b", s)
    if temp:
        feats["temperature"] = [f"{t}°c" for t in temp]

    life = re.findall(r"(\d{3,6})\s*(?:h|小时)\b", s)
    if life:
        feats["life_hours"] = life

    pkg = PACKAGES.findall(s)
    if pkg:
        feats["package"] = sorted(set(pkg))

    diel = sorted({t for t in tokenize(s) if t in DIELECTRIC})
    if diel:
        feats["dielectric"] = diel

    return feats
