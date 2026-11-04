"""
core/classify/similarity.py — 三个相似度信号

【这个模块做什么】
给"规格描述 ↔ 类目"打分。单一算法都不够，所以用三个信号加权融合：

    ① 关键词命中（权重 0.50）：领域强信号，"铝电解"三个字出现基本就定了。
    ② IDF 加权覆盖率（0.30）：描述里的信息有多少被该类目覆盖。用 IDF 加权是因为
       "电容""50v" 这种处处出现的词不该加分，"x7r""氮化铝" 这种稀有词才该加分。
    ③ 字符 n-gram 包含率（0.20）：兜住错别字与缩写（"陶磁电容" vs "陶瓷电容"）。

【在整条流程中的位置】
    normalize 后的文本 + 知识库 → similarity → engine 融合打分与分流

【为什么不用"编辑距离"做主信号】
中文短描述的编辑距离几乎被"长度差"主导：描述 30 字、类目文档 80 字，
两者编辑距离天然很大，和内容对不对无关。字符 n-gram 的**包含率**（而不是对称的 Jaccard）
对"短查询 vs 长文档"更稳，这是本项目的取舍。

【为什么不用 embedding】
需求明确要求"不依赖联网 API"。本地 embedding 模型（如 bge-small）需要下载几百 MB 权重，
且对"BOM 缩写 + 数字"这类文本优势不大——关键词命中的可解释性反而更适合工程场景：
用户能看懂"为什么被判成铝电解"，也能自己改关键词去修正。
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from .normalize import clean_tokens, normalize_text

# 关键词权重归一化尺度：命中 6 分权重视为"强匹配"（=1.0）。
# 之所以不用"命中权重 / 该类目全部关键词权重"，是因为一条描述永远只会命中少数几个词，
# 用总量归一化会把所有得分压到 0.3 以下，0.7 / 0.3 两个阈值就失去意义了。
KW_SCALE = 6.0

# 负向关键词的惩罚系数：每命中一个，得分乘 0.45（最多叠 2 次）。
# 为什么用乘法而不是减法：保证"命中强正向词 + 命中排除词"仍可能被判为待确认，
# 而不是直接掉到 0——人工确认队列正是为这种情况准备的。
NEGATIVE_PENALTY = 0.45
NEGATIVE_MAX_STACK = 2

# 纯数字/单位 token 的信息量很低（几乎所有类目都有 50v、0.1、0603），
# 在 IDF 覆盖里打 0.2 折，避免"数字对上就算相似"的假高分。
NUMERIC_LIKE_PENALTY = 0.2


def compact(text: str) -> str:
    """归一化并去掉所有空格。用于"关键词 vs 描述"的严格子串匹配。

    为什么去空格：描述里 "1000 uF" 与关键词 "1000uF" 必须等价；
    "105 °c" 与 "105℃" 必须等价。不去空格，这类命中会静默丢失。
    """
    return normalize_text(text, drop_noise=False).replace(" ", "")


def keyword_score(
    norm_text: str, keywords: Sequence[Dict[str, object]], negatives: Sequence[str]
) -> Tuple[float, List[str], List[str]]:
    """返回 (得分, 命中词, 命中排除词)。

    注意：norm_text 与 keywords 都必须已经过 compact() 处理（去空格、统一单位写法）。
    否则关键词 "105℃" 永远匹配不上描述里的 "105 °c"——这是本项目实际踩过的坑。
    """
    hit_weight = 0.0
    hits: List[str] = []
    for kw in keywords:
        k = str(kw.get("k", "")).strip().lower()
        if not k:
            continue
        if k in norm_text:
            hit_weight += float(kw.get("w", 1))
            hits.append(k)

    score = min(1.0, hit_weight / KW_SCALE)

    neg_hits = [n.lower() for n in negatives if n and n.lower() in norm_text]
    if neg_hits:
        score *= NEGATIVE_PENALTY ** min(len(neg_hits), NEGATIVE_MAX_STACK)

    return score, hits, neg_hits


def _token_weight(token: str, idf: Dict[str, float], default_idf: float) -> float:
    w = idf.get(token, default_idf)
    if token.isdigit() or token.replace(".", "", 1).isdigit():
        w *= NUMERIC_LIKE_PENALTY
    if token in {"v", "a", "w", "uf", "nf", "pf", "ω", "kω", "mω", "h", "mm", "°c", "%"}:
        w *= 0.2
    return w


def idf_coverage(
    query_tokens: Iterable[str], doc_tokens: Set[str], idf: Dict[str, float], default_idf: float = 3.0
) -> float:
    """描述中的信息有多少被该类目文档"覆盖"（IDF 加权，0~1）。"""
    q = [t for t in clean_tokens(list(query_tokens)) if len(t) >= 1]
    if not q:
        return 0.0
    num = 0.0
    den = 0.0
    for t in q:
        w = _token_weight(t, idf, default_idf)
        den += w
        if t in doc_tokens:
            num += w
    return num / den if den else 0.0


def char_ngrams(text: str, n: int = 3) -> Set[str]:
    s = "".join(text.split())
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def char_containment(query_text: str, doc_text: str, n: int = 3) -> float:
    """查询的字符 n-gram 有多大比例出现在文档里（非对称，适合短查询 vs 长文档）。"""
    q = char_ngrams(query_text, n)
    if not q:
        return 0.0
    d = char_ngrams(doc_text, n)
    return len(q & d) / len(q)


def build_idf(docs: Sequence[List[str]]) -> Tuple[Dict[str, float], float]:
    """标准 IDF：log(N / (1 + df)) + 1。返回 (idf 表, 未登录词的默认值)。"""
    n_docs = max(1, len(docs))
    df: Counter = Counter()
    for toks in docs:
        for t in set(toks):
            df[t] += 1
    idf = {t: math.log(n_docs / (1 + c)) + 1.0 for t, c in df.items()}
    default = math.log(n_docs / 1.0) + 1.0
    return idf, default


def fuse(keyword: float, idf_cov: float, char_sim: float) -> float:
    """三信号加权融合。权重依据见模块头部说明，改动此值等于改动系统的判定口径。"""
    return 0.50 * keyword + 0.30 * idf_cov + 0.20 * char_sim
