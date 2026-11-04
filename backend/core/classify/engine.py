"""
core/classify/engine.py — 分类匹配引擎（含知识库自学习）

【这个模块做什么】
把一条规格描述判到一个二级类目上（如 CAP_ALU 铝电解电容），并给出置信度与候选，
按置信度分流到三条路径：

    ≥ 0.70            → auto          自动归类，用户不用管
    0.30 ~ 0.70       → pending_review 给出建议 + Top3 候选，进人工确认队列
    < 0.30            → unrecognized   标记未识别，必须人工指定

另外两条补充规则（工程上很实用，标准阈值解决不了）：
    · 若 Top1 与 Top2 的分差 < 0.05，即使 Top1 ≥ 0.70 也降级为待确认——
      两个类目分数几乎一样时，机器其实"没把握"，硬判就是埋雷。
    · 大类（电容/电阻/…）与小类一起打分，但输出时按大类聚合展示，方便人工按类核对。

【在整条流程中的位置】
    BOM 描述 → normalize → similarity → **本模块** → 分类结果（含理由）→ 页面/数据库

【为什么"理由"必须输出】
分类是"机器给建议、人拍板"的流程。如果界面只显示「CAP_ALU 0.87」，工程师无从判断
该不该信。所以每个结果都带：命中了哪些关键词、被哪些排除词扣分、各类信号的分数。
这既是可用性问题，也是信任问题——可解释的分类才会被真正使用。

【自学习怎么防止"越学越乱"】
人工改判后不能直接把整条描述塞进知识库（会导致关键词表爆炸且泛化极差），
本模块的做法是抽取"区别性片段"：
    1. 把描述分词，去掉停用词、数字、单位；
    2. 去掉"目标类目已有关键词"里的词（那些不是区别性信息）；
    3. 优先选出现在"目标类目样例描述"里、但不在"误判类目关键词"里的词；
    4. 最多取 2 个，权重从 2 起步；同一词被独立确认 3 次以上才升权。
同时向误判类目写一条负向词，避免下次再错。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

from . import similarity
from .normalize import clean_tokens, extract_features, normalize_text, tokenize, tokens_of


AUTO_THRESHOLD = 0.70
REVIEW_THRESHOLD = 0.30
AMBIGUITY_MARGIN = 0.05  # Top1 与 Top2 的分差小于此值时降级为待确认

# 位号前缀 → 大类。来自通用原理图位号惯例：R 电阻、C 电容、L 电感、D 二极管、
# Q 晶体管、U 集成电路、J/CN 连接器、Y 晶振、F 保险丝、K 继电器、SW 开关、W 线缆。
# 【为什么这是最值钱的一个信号】BOM 描述常常写得含糊（"电容 0.1uF 50V 0603" 到底是
# 陶瓷还是薄膜？），但位号前缀是不会含糊的——C 开头就是电容。只按描述打分时，
# 这类模糊行只能进人工队列；带上位号后就可以直接用大方向兜住，把候选范围收窄一个数量级。
# 注意：它只能定"大类"，定不了"小类"（C3 是陶瓷还是铝电解还得看描述），所以是加分项，不是判决。
REFDES_MAJOR = {
    "PCB": "EM", "LED": "LED_G", "SW": "SWITCH_G", "RP": "RES", "IC": "IC",
    "CN": "CONN", "PS": "MODULE", "R": "RES", "C": "CAP", "L": "IND",
    "D": "DIO", "Q": "TRA", "U": "IC", "J": "CONN", "P": "CONN",
    "Y": "XTAL_G", "F": "FUSE_G", "K": "RELAY_G", "B": "EM", "S": "EM",
    "W": "CABLE", "X": "MECH",
}

# 位号加成：命中同大类时加 0.10（不乘系数，避免把 0.05 的噪声放大成 0.06 假象）。
# 只对"本来就有一点分"的候选生效（>=0.10），否则任何一个词都能被位号抬进待确认队列。
DESIGNATOR_BONUS = 0.10
DESIGNATOR_MIN_SCORE = 0.10


def _designator_major(ref_des: Optional[str]) -> Optional[str]:
    """从位号（R12 / LED3 / PCB1）推断所属大类；推不出返回 None。

    只取前缀字母并按长度优先匹配——"LED3" 要匹配 LED 而不是 L（电感），
    "PCB1" 要匹配 PCB 而不是 P（连接器）。这个顺序搞反会把整批 LED 判成电感。
    """
    if not ref_des:
        return None
    letters = "".join(ch for ch in str(ref_des).strip().upper() if ch.isalpha())
    if not letters:
        return None
    for key in sorted(REFDES_MAJOR, key=len, reverse=True):
        if letters.startswith(key):
            return REFDES_MAJOR[key]
    return None


@dataclass
class Candidate:
    code: str
    name: str
    parent: str
    score: float
    keyword_score: float
    idf_score: float
    char_score: float
    hits: List[str] = field(default_factory=list)
    negatives: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category_code": self.code,
            "category_name": self.name,
            "parent": self.parent,
            "score": round(self.score, 4),
            "keyword_score": round(self.keyword_score, 4),
            "idf_score": round(self.idf_score, 4),
            "char_score": round(self.char_score, 4),
            "hits": self.hits,
            "negatives": self.negatives,
        }


@dataclass
class MatchResult:
    description: str
    status: str                      # auto / pending_review / unrecognized
    best: Optional[Candidate]
    candidates: List[Candidate]
    reason: str
    features: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "status": self.status,
            "best": self.best.to_dict() if self.best else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "reason": self.reason,
            "features": self.features,
        }


class Classifier:
    """分类器。构造时把知识库编译成索引（文档 token 集合 + IDF 表）。"""

    def __init__(self, kb: Dict[str, Any]):
        self.major = kb.get("major_categories", [])
        self.categories = kb.get("categories", [])
        self.major_name = {m["code"]: m["name"] for m in self.major}

        self._docs: Dict[str, Set[str]] = {}
        self._doc_text: Dict[str, str] = {}
        self._kw: Dict[str, Sequence[Dict[str, Any]]] = {}
        self._neg: Dict[str, Sequence[str]] = {}

        token_lists: List[List[str]] = []
        for c in self.categories:
            # 类目文档 = 名称 + 别名 + 定义 + 样例描述。
            # 加上"定义"和"样例"是为了让 IDF 覆盖有足够上下文；
            # 只放名称的话，"0.1uf 50v 0603" 这类描述几乎覆盖不到任何东西。
            doc_text = " ".join([c.name, " ".join(c.aliases), c.description, " ".join(c.samples)])
            toks = clean_tokens(tokens_of(doc_text))
            self._docs[c.code] = set(toks)
            self._doc_text[c.code] = normalize_text(doc_text)
            # 关键词与排除词预编译成"紧凑形式"（去空格 + 统一单位写法），
            # 与描述文本在同一口径下做子串匹配。这一步不做，关键词基本全废。
            self._kw[c.code] = [
                {"k": similarity.compact(str(k.get("k", ""))), "w": float(k.get("w", 1))}
                for k in c.keywords
                if str(k.get("k", "")).strip()
            ]
            self._neg[c.code] = [similarity.compact(n) for n in c.negatives if str(n).strip()]
            token_lists.append(toks)

        self._idf, self._default_idf = similarity.build_idf(token_lists)

    # ------------------------------------------------------------------
    def classify(
        self, description: str, forced_major: Optional[str] = None, ref_des: Optional[str] = None
    ) -> MatchResult:
        norm = normalize_text(description)
        features = extract_features(description)

        # 位号前缀只能提示"大类"，用于给同大类的候选加分（见模块头部说明）
        hint_major = _designator_major(ref_des)
        if hint_major:
            features["refdes_major"] = hint_major

        if not norm or len(norm) < 2:
            return MatchResult(
                description=description,
                status="unrecognized",
                best=None,
                candidates=[],
                reason="描述为空或过短（少于 2 个字符），无法匹配，请人工指定分类。",
                features=features,
            )

        q_tokens = tokenize(norm)
        norm_compact = norm.replace(" ", "")
        candidates: List[Candidate] = []

        for c in self.categories:
            if forced_major and c.parent != forced_major:
                continue
            kw_s, hits, neg_hits = similarity.keyword_score(
                norm_compact, self._kw[c.code], self._neg[c.code]
            )
            idf_s = similarity.idf_coverage(q_tokens, self._docs[c.code], self._idf, self._default_idf)
            char_s = similarity.char_containment(norm, self._doc_text[c.code])
            # 样例描述往往比"定义"更接近真实写法，取两者最大值，避免定义写得长而拉低相似度
            for sample in c.samples:
                char_s = max(char_s, similarity.char_containment(norm, normalize_text(sample)))

            score = similarity.fuse(kw_s, idf_s, char_s)
            if hint_major and c.parent == hint_major and score >= DESIGNATOR_MIN_SCORE:
                score = min(1.0, score + DESIGNATOR_BONUS)
            candidates.append(
                Candidate(
                    code=c.code,
                    name=c.name,
                    parent=c.parent,
                    score=score,
                    keyword_score=kw_s,
                    idf_score=idf_s,
                    char_score=char_s,
                    hits=hits,
                    negatives=neg_hits,
                )
            )

        candidates.sort(key=lambda x: x.score, reverse=True)
        top = candidates[:3]
        best = top[0] if top else None

        if best is None:
            return MatchResult(description, "unrecognized", None, [], "没有可用的候选类目。", features)

        # ---- 分流判定 ----
        if best.score < REVIEW_THRESHOLD:
            status = "unrecognized"
            reason = (
                f"最高相似度仅 {best.score:.0%}（< 30%），未达到任何类目的最低可信度。"
                f"最接近的是「{best.name}」，但证据不足，请人工指定。"
            )
        elif best.score < AUTO_THRESHOLD:
            status = "pending_review"
            reason = (
                f"相似度 {best.score:.0%} 落在 30%~70% 区间，建议归类为「{best.name}」，"
                "需要人工确认。"
            )
        else:
            second = top[1] if len(top) > 1 else None
            if second and (best.score - second.score) < AMBIGUITY_MARGIN:
                status = "pending_review"
                reason = (
                    f"「{best.name}」({best.score:.0%}) 与「{second.name}」({second.score:.0%}) 得分过于接近，"
                    "机器无法可靠区分，请人工确认。"
                )
            else:
                status = "auto"
                reason = (
                    f"相似度 {best.score:.0%} ≥ 70%，自动归类为「{best.name}」"
                    f"（命中关键词：{'、'.join(best.hits[:4]) or '无'}）。"
                )

        if best.negatives:
            reason += f" 注意：描述中出现了排除词（{'、'.join(best.negatives)}），已扣减该候选得分。"

        if hint_major:
            reason += (
                f" 位号前缀提示大类为「{self.major_name.get(hint_major, hint_major)}」，"
                "已给该大类候选加分。"
            )

        return MatchResult(description, status, best, top, reason, features)

    # ------------------------------------------------------------------
    def classify_many(self, descriptions: Sequence[str]) -> List[MatchResult]:
        return [self.classify(d) for d in descriptions]

    def stats(self, results: Sequence[MatchResult]) -> Dict[str, Any]:
        counts = {"auto": 0, "pending_review": 0, "unrecognized": 0}
        by_major: Dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
            if r.best:
                m = self.major_name.get(r.best.parent, r.best.parent)
                by_major[m] = by_major.get(m, 0) + 1
        total = len(results) or 1
        return {
            "total": len(results),
            **counts,
            "auto_pct": round(counts["auto"] / total * 100, 1),
            "by_major": by_major,
        }


# ---------------------------------------------------------------------------
# 自学习：把人工确认结果沉淀成关键词
# ---------------------------------------------------------------------------

_TOKEN_STOP = {
    "贴片", "插件", "原装", "环保", "无铅", "rohs", "电容", "电阻", "电感", "二极管",
    "三极管", "芯片", "型号", "规格", "封装", "品牌", "数量", "元件", "器件",
}


def suggest_keywords(
    description: str,
    target_code: str,
    wrong_code: Optional[str],
    kb: Dict[str, Any],
    max_new: int = 2,
) -> Dict[str, List[str]]:
    """从一次人工改判中提取"区别性片段"，返回 {add: [...], negative: [...]}。

    只做建议，落库由调用方决定——知识库被污染比分类不准更麻烦。
    """
    cats = {c.code: c for c in kb.get("categories", [])}
    target = cats.get(target_code)
    if target is None:
        return {"add": [], "negative": []}

    existing = {str(k.get("k", "")).lower() for k in target.keywords}
    wrong_kw = {str(k.get("k", "")).lower() for k in cats[wrong_code].keywords} if wrong_code in cats else set()

    toks = clean_tokens(tokenize(normalize_text(description)))
    usable = []
    for t in toks:
        if len(t) < 2 or t in _TOKEN_STOP or t in existing:
            continue
        if t.isdigit() or t.replace(".", "", 1).isdigit():
            continue
        if t in {"v", "a", "w", "uf", "nf", "pf", "ω", "kω", "mω", "h", "mm", "°c", "%"}:
            continue
        usable.append(t)

    # 优先级1：出现在目标类目样例里、但不在误判类目关键词里的词 → 最能说明"这才是对的"
    target_samples = normalize_text(" ".join(target.samples))
    prioritized = [t for t in usable if t in target_samples and t not in wrong_kw]
    rest = [t for t in usable if t not in prioritized]

    add = list(dict.fromkeys(prioritized + rest))[:max_new]

    negative = []
    if wrong_code:
        # 如果误判类目的名字/别名里的某个词出现在了描述中，但目标类目不该有它，
        # 就把它作为目标类目的排除词。保守起见只在该词长度 ≥2 时采用。
        for alias in cats[wrong_code].aliases:
            a = normalize_text(alias)
            if a and len(a) >= 2 and a in normalize_text(description) and a not in target_samples:
                negative.append(a)
                break

    return {"add": add, "negative": negative}
