"""
app/services/report.py — 评估报告生成（PDF / XLSX）

【这个模块做什么】
把一次评估的完整结果渲染成两种可交付文件：
    PDF  — 给人看、给客户/评审看，结构对齐专业预计报告；
    XLSX — 给人算、给二次分析用，一表一主题。

【报告结构（与需求文档第 7 节对应）】
    1. 封面（项目/版本/标准/引擎与参数库版本/判定）
    2. 评估范围与假设（四参数 + 目标 + 缺失数据说明）
    3. BOM 分类明细（按大类汇总）
    4. 可靠性预计结果（双标准并排对比）
    5. 短板 Top10（贡献占比 + 累计占比）
    6. 磨损寿命评估（排行榜 + 整机结论）
    7. 降额检查（违规优先）
    8. 敏感性摘要
    9. 综合结论与改进建议
    10. 附录 A 计算明细 / 附录 B 参数来源 / 附录 C 免责声明

【中文字体（Windows 部署的关键坑）】
reportlab 内置字体不含中文，不注册 TTF 的话所有汉字变成黑方块。
这里按 msyh → simhei → simsun 的顺序找系统字体，并用 ttc 的子字体索引取简体常规体。
找不到就退回 Helvetica 并在报告里明确标注「字体缺失，中文可能显示异常」——
宁可显式报警，也不要交付一份看不懂的文件。
"""

from __future__ import annotations

import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from core.calc import compare_standards as core_compare
from core.standards.loader import load_param_set, load_derating_rules, load_wear_models

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..config import settings

CN_FONT = "Helvetica"
CN_FONT_BOLD = "Helvetica-Bold"
FONT_NOTE = ""

_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/msyh.ttc", 0, "MSYH"),
    ("C:/Windows/Fonts/msyh.ttf", None, "MSYH"),
    ("C:/Windows/Fonts/simhei.ttf", None, "SIMHEI"),
    ("C:/Windows/Fonts/simsun.ttc", 0, "SIMSUN"),
    ("/System/Library/Fonts/PingFang.ttc", 0, "PINGFANG"),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0, "WQY"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0, "NOTO"),
]


def _register_cn_font() -> None:
    global CN_FONT, CN_FONT_BOLD, FONT_NOTE
    for path, index, name in _FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            if index is None:
                pdfmetrics.registerFont(TTFont(name, path))
            else:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=index))
            CN_FONT = name
            CN_FONT_BOLD = name          # 不另找粗体：雅黑本体够粗，避免字体回退导致缺字
            FONT_NOTE = ""
            return
        except Exception:
            continue
    FONT_NOTE = "警告：未找到可用中文字体，PDF 中的中文可能显示异常。请安装微软雅黑或思源黑体。"


_register_cn_font()


# ---------------------------------------------------------------------------
# 样式
# ---------------------------------------------------------------------------

SECTION_COLORS = {
    "PASS": colors.HexColor("#1B7F3B"),
    "FAIL": colors.HexColor("#C0392B"),
}


def _styles() -> Dict[str, ParagraphStyle]:
    _register_cn_font()
    base = getSampleStyleSheet()
    st = {
        "title": ParagraphStyle("title", parent=base["Title"], fontName=CN_FONT, fontSize=22, leading=30, alignment=TA_CENTER),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontName=CN_FONT, fontSize=11, leading=18, alignment=TA_CENTER, textColor=colors.HexColor("#555555")),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName=CN_FONT, fontSize=14, leading=20, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#1F3864")),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName=CN_FONT, fontSize=11.5, leading=16, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#2E5496")),
        "body": ParagraphStyle("body", parent=base["Normal"], fontName=CN_FONT, fontSize=9.2, leading=14.5, alignment=TA_LEFT, wordWrap="CJK"),
        "small": ParagraphStyle("small", parent=base["Normal"], fontName=CN_FONT, fontSize=8, leading=12, textColor=colors.HexColor("#666666"), wordWrap="CJK"),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontName=CN_FONT, fontSize=8, leading=11.5, wordWrap="CJK"),
    }
    return st


def _tbl(data: List[List[Any]], widths: Optional[List[float]] = None, header_bg: str = "#1F3864") -> Table:
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), CN_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFC9D9")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5FA")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t


def _fmt(v: Any, digits: int = 2) -> str:
    if v is None or v == "null":
        return "—"
    if isinstance(v, (int, float)):
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        return f"{v:,.{digits}f}"
    return str(v)


def _pareto_chart(rows: List[Dict[str, Any]], width: float = 480) -> Drawing:
    """短板 Pareto 横条图。只用矩形 + 文字，避开 reportlab 图表对中文字体的兼容坑。"""
    top = rows[:8]
    bar_h = 16
    gap = 6
    height = max(60, len(top) * (bar_h + gap) + 20)
    d = Drawing(width, height)
    max_v = max([r["lambda_part"] for r in top] or [1]) or 1
    label_w = 110
    for i, r in enumerate(top):
        y = height - (i + 1) * (bar_h + gap)
        d.add(String(0, y + 4, str(r["part_number"])[:18], fontName=CN_FONT, fontSize=7.5))
        w = (width - label_w - 70) * (r["lambda_part"] / max_v)
        d.add(Rect(label_w, y, max(1.5, w), bar_h, fillColor=colors.HexColor("#3A6EA5"), strokeColor=None))
        d.add(
            String(
                label_w + max(1.5, w) + 4,
                y + 4,
                f'{r["lambda_part"]:.2f} FIT / {r["contribution_pct"]:.1f}%',
                fontName=CN_FONT,
                fontSize=7,
            )
        )
    return d


# ---------------------------------------------------------------------------
# 报告内容组装
# ---------------------------------------------------------------------------


def _assumption_lines(payload: Dict[str, Any], param_meta: Dict[str, Any]) -> List[List[str]]:
    a = payload.get("assumptions", {})
    duty = a.get("duty_cycle", 0) or 0
    env_label = "—"
    for e in param_meta.get("environments", []):
        if e["code"] == a.get("environment"):
            env_label = f'{e["code"]} · {e["label"]}（π_E={e["mult"]}）'
    q_label = "—"
    for q in param_meta.get("quality_levels", []):
        if q["code"] == a.get("quality_level"):
            q_label = f'{q["code"]} · {q["label"]}（π_Q={q["pi_q"]}）'

    return [
        ["参数", "取值", "说明"],
        ["工作环境类别", env_label, "决定 π_E，是全机失效率的基准倍率"],
        ["环境温度", f'{_fmt(a.get("ambient_temp_c"), 1)} °C', "决定 π_T 与磨损寿命"],
        ["元件质量等级", q_label, "决定 π_Q，质量等级差异可达数倍"],
        ["日通电时长", f'{_fmt(a.get("duty_hours_per_day"), 1)} h/日（duty={duty:.3f}）', "折算 R(t) 的时间轴与磨损年限"],
        ["目标年限 / 存活率", f'{_fmt(a.get("target_years"), 1)} 年 / {(_fmt(a.get("target_survival"), 3))}', "判定依据"],
        ["MTBF 门槛", _fmt(a.get("mtbf_threshold_hours"), 0) + " h" if a.get("mtbf_threshold_hours") else "未设置", "可选的第二道判定闸"],
        ["计算标准 / 模式", f'{a.get("standard")} / {"零件计数法" if a.get("mode") == "parts_count" else "零件应力法"}', "两套标准口径不同，不可混用"],
    ]


def _suggestions(payload: Dict[str, Any]) -> List[str]:
    """自动生成改进建议。不是套话，每条都从结果里推出来。"""
    out: List[str] = []
    a = payload.get("assessment", {})
    top = a.get("top_contributors", [])
    wear = payload.get("wear", {}) or {}
    der = payload.get("derating", {}) or {}
    sens = payload.get("sensitivity", {}) or {}

    if top:
        biggest = top[0]
        out.append(
            f"换料优先级：{biggest['part_number']}（{biggest.get('category_name','')}）贡献了整机失效率的 "
            f"{biggest['contribution_pct']:.1f}%，是最大的单点短板。优先核对其用量与工作条件；确认无误后，"
            "考虑换用同规格但质量等级更高的料，或降低其工作温度/电压应力。"
        )
        acc = 0.0
        for r in top:
            acc += r["contribution_pct"]
            if acc >= 60:
                out.append(
                    f"前 {top.index(r)+1} 个零件已占总失效率的 {acc:.0f}%（帕累托前段），"
                    "改进应集中在这几项，其余零件的优化收益很小。"
                )
                break

    violations = [d for d in der.get("items", []) if d.get("verdict") == "violation"]
    if violations:
        names = "、".join(f"{d['part_number']}({d['stress_type']})" for d in violations[:5])
        out.append(
            f"降额违规 {len(violations)} 项，必须整改：{names}。"
            "降额是最低成本、见效最快的可靠性改进手段，建议在下一版直接更换更高额定值的料。"
        )

    marg = [d for d in der.get("items", []) if d.get("verdict") == "marginal"]
    if marg:
        out.append(f"另有 {len(marg)} 项落在「接近上限」区，余量已很薄，建议一并调整或做温升实测确认。")

    if wear.get("mechanism_kind") == "wear" and wear.get("limiting_mechanism"):
        out.append(
            f"寿命受限于磨损机理：{wear['limiting_mechanism']}，预计 {('%.1f' % wear['t_wear_years']) if wear.get('t_wear_years') else '—'} 年。"
            "这类失效无法通过提高 MTBF 改善，只能换长寿命料或降低其工作温度/动作频次。"
        )
    elif wear.get("mechanism_kind") == "random":
        out.append("寿命由随机失效主导（磨损件不是短板），可通过提升器件质量等级或降低环境严酷度改善。")

    temp_rank = (sens.get("ranking") or [False])[0]
    if temp_rank:
        out.append(
            f"敏感性最大的假设是「{temp_rank['variable']}」（{temp_rank['change']} 使 MTBF 变化 "
            f"{temp_rank['delta_pct']:.0f}%）。建议优先核实这条假设的真实性——结论对它的依赖最强。"
        )

    missing = sum(1 for p in a.get("parts", []) for s in p.get("trace", []) if s.get("is_default"))
    if missing:
        out.append(
            f"有 {missing} 处计算使用了默认应力/温升（追溯明细中标为「默认」）。"
            "补录真实工作电压、功耗与温升后重算，结论会更可靠。"
        )

    out.append(
        "本报告为理论预计，精度为数量级参考。若用于对外承诺或认证，必须通过 RDT 实测"
        "（高温工作寿命、温循、振动）或现场数据验证。"
    )
    return out


def _build_story(project: Dict[str, Any], payload: Dict[str, Any], param_meta: Dict[str, Any], generated_at: str) -> List[Any]:
    st = _styles()
    a = payload.get("assessment", {})
    wear = payload.get("wear", {}) or {}
    der = payload.get("derating", {}) or {}
    sens = payload.get("sensitivity", {}) or {}
    verdict = a.get("verdict", "NA")

    story: List[Any] = []

    # ---- 封面 ----
    story.append(Spacer(1, 40 * mm))
    story.append(Paragraph("电子零件可靠性评估报告", st["title"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(f'{project.get("name","")}　（{project.get("code","")}）', st["subtitle"]))
    story.append(Spacer(1, 12 * mm))

    verdict_color = SECTION_COLORS.get(verdict, colors.HexColor("#7F7F7F"))
    vt = Table(
        [[Paragraph(f'<font color="white" size="16">综合判定：{verdict}</font>', ParagraphStyle("v", fontName=CN_FONT, alignment=TA_CENTER))]],
        colWidths=[70 * mm],
    )
    vt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), verdict_color), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story.append(vt)
    story.append(Spacer(1, 10 * mm))

    cover_rows = [
        ["项目名称", project.get("name", "")],
        ["项目编号", project.get("code", "")],
        ["BOM 版本", project.get("bom_label", "")],
        ["计算标准", f'{param_meta.get("display_name", a.get("standard",""))}（{a.get("param_version","")}）'],
        ["计算模式", "零件计数法 Parts Count" if a.get("mode") == "parts_count" else "零件应力法 Parts Stress"],
        ["引擎版本", a.get("engine_version", "")],
        ["目标年限 / 存活率", f'{_fmt(project.get("target_years"),1)} 年 / {_fmt(project.get("target_survival"),3)}'],
        ["整机失效率", f'{_fmt(a.get("lambda_total_fit"),3)} FIT'],
        ["整机 MTBF", f'{_fmt(a.get("mtbf_hours"),0)} h'],
        ["目标年限存活率", f'{_fmt(a.get("r_at_target"),4)}'],
        ["生成时间", generated_at],
    ]
    story.append(_tbl(cover_rows, widths=[45 * mm, 105 * mm]))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(param_meta.get("disclaimer", ""), st["small"]))
    if FONT_NOTE:
        story.append(Paragraph(FONT_NOTE, st["small"]))
    story.append(PageBreak())

    # ---- 1. 范围与假设 ----
    story.append(Paragraph("1. 评估范围与假设", st["h1"]))
    story.append(
        Paragraph(
            f'本次评估覆盖 BOM 共 {project.get("row_count", 0)} 行、元件总数 {project.get("qty_total", 0)} 只，'
            f'全部零件已完成分类。评估对象为整机的随机失效率（不含结构件、线缆、包装等未列入 BOM 的项目）。'
            "读结论前请先确认下表四个假设——整份报告的可信度由它们决定。",
            st["body"],
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(_tbl(_assumption_lines(payload, param_meta), widths=[38 * mm, 62 * mm, 50 * mm]))

    reasons = a.get("verdict_reasons", [])
    if reasons:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("判定依据", st["h2"]))
        for r in reasons:
            story.append(Paragraph(f"· {r}", st["body"]))

    warns = [w for w in a.get("warnings", []) if w]
    if warns:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("需要注意的假设风险", st["h2"]))
        for w in warns[:6]:
            story.append(Paragraph(f"· {w}", st["body"]))

    # ---- 2. 结果 ----
    story.append(Paragraph("2. 可靠性预计结果", st["h1"]))
    res_rows = [
        ["指标", "数值", "读法"],
        ["整机失效率 λ_total", f'{_fmt(a.get("lambda_total_fit"),3)} FIT', "每 10 亿小时失效次数，越小越好"],
        ["整机 MTBF", f'{_fmt(a.get("mtbf_hours"),0)} h', "平均失效间隔，注意不是寿命"],
        ["目标年限通电小时", f'{_fmt(a.get("operating_hours"),0)} h', "= 年限 × 8760 × duty"],
        ["目标年限存活率 R(t)", f'{_fmt(a.get("r_at_target"),4)}', "主判据：是否达到目标的存活率"],
        ["判定", verdict, "存活率达标且（若设门槛）MTBF 达标"],
    ]
    story.append(_tbl(res_rows, widths=[45 * mm, 40 * mm, 65 * mm]))

    # 冗余（若有）
    red = a.get("redundancy", [])
    if red:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("冗余组（可靠性框图）", st["h2"]))
        rows = [["组", "成员数", "按串联的合计 λ", "并联等效 λ", "组存活率"]]
        for g in red:
            rows.append([g["group"], len(g["member_ids"]), _fmt(g["member_lambda_sum"], 3), _fmt(g["lambda_equiv"], 3), _fmt(g["r_group"], 5)])
        story.append(_tbl(rows, widths=[35 * mm, 22 * mm, 38 * mm, 32 * mm, 28 * mm]))
        story.append(Paragraph("提示：并联收益按「共因失效可忽略」计算，是收益上限。", st["small"]))

    # ---- 3. 短板 ----
    story.append(PageBreak())
    story.append(Paragraph("3. 短板分析（贡献排序）", st["h1"]))
    story.append(Paragraph("按零件失效率贡献降序排列。换料应自上而下进行——前几项决定了整机水平。", st["body"]))
    story.append(Spacer(1, 2 * mm))
    top = a.get("top_contributors", [])
    if top:
        rows = [["排名", "料号", "类别", "用量", "λ (FIT)", "占比", "累计"]]
        for i, r in enumerate(top, 1):
            rows.append([i, r["part_number"], r.get("category_name", ""), r["qty"], _fmt(r["lambda_part"], 3), f'{r["contribution_pct"]:.2f}%', f'{r.get("cumulative_pct", 0):.1f}%'])
        story.append(_tbl(rows, widths=[12 * mm, 48 * mm, 35 * mm, 14 * mm, 24 * mm, 18 * mm, 18 * mm]))
        story.append(Spacer(1, 4 * mm))
        story.append(_pareto_chart(top))
    else:
        story.append(Paragraph("无短板数据。", st["body"]))

    # ---- 4. 双标准对比 ----
    story.append(Paragraph("4. 双标准对比", st["h1"]))
    dual = payload.get("dual_standard") or {}
    if dual.get("standards"):
        rows = [["标准", "λ_total (FIT)", "MTBF (h)", "R(t)", "判定"]]
        for std, s in dual["standards"].items():
            rows.append([s.get("display_name", std), _fmt(s["lambda_total_fit"], 3), _fmt(s["mtbf_hours"], 0), _fmt(s["r_at_target"], 4), s["verdict"]])
        story.append(_tbl(rows, widths=[62 * mm, 30 * mm, 30 * mm, 24 * mm, 18 * mm]))
        story.append(Paragraph(dual.get("note", ""), st["small"]))
    else:
        story.append(Paragraph("本次评估未附双标准对比结果（可在系统中重新运行对比）。", st["body"]))

    # ---- 5. 磨损 ----
    story.append(PageBreak())
    story.append(Paragraph("5. 磨损寿命评估", st["h1"]))
    if wear:
        story.append(Paragraph(wear.get("conclusion", ""), st["body"]))
        story.append(Spacer(1, 2 * mm))
        items = wear.get("items", [])[:12]
        if items:
            rows = [["料号", "机理", "寿命 (h)", "折算年限", "是否限制项"]]
            for w in items:
                rows.append([w["part_number"], w["mechanism_label"], _fmt(w["life_hours"], 0), _fmt(w["life_years"], 1), "★" if w.get("is_limiting") else ""])
            story.append(_tbl(rows, widths=[52 * mm, 42 * mm, 28 * mm, 22 * mm, 20 * mm]))
        if items and items[0].get("formula"):
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph("最短板件的计算式", st["h2"]))
            story.append(Paragraph(items[0]["formula"], st["small"]))
        story.append(Paragraph(wear.get("disclaimer", ""), st["small"]))
    else:
        story.append(Paragraph("BOM 中未识别到有磨损模型的关键件（电解电容/风扇/继电器/LED/连接器）。", st["body"]))

    # ---- 6. 降额 ----
    story.append(Paragraph("6. 降额检查（Derating）", st["h1"]))
    if der:
        story.append(Paragraph(der.get("summary", {}).get("conclusion", ""), st["body"]))
        story.append(Spacer(1, 2 * mm))
        bad = [d for d in der.get("items", []) if d["verdict"] in ("violation", "marginal")][:15]
        if bad:
            rows = [["料号", "应力类型", "额定值", "工作值", "比值", "规范上限", "判定"]]
            for d in bad:
                rows.append([
                    d["part_number"], d["stress_type"], _fmt(d["rated_value"], 2), _fmt(d["applied_value"], 2),
                    f'{d["ratio"]:.1%}' if d.get("ratio") is not None else "—",
                    f'{d["max_ratio"]:.0%}',
                    {"violation": "超限", "marginal": "接近"}.get(d["verdict"], d["verdict"]),
                ])
            story.append(_tbl(rows, widths=[46 * mm, 20 * mm, 20 * mm, 20 * mm, 18 * mm, 22 * mm, 16 * mm]))
        else:
            story.append(Paragraph("未发现超限或接近上限的项目。", st["body"]))
        story.append(Paragraph(der.get("disclaimer", ""), st["small"]))
    else:
        story.append(Paragraph("未执行降额检查。", st["body"]))

    # ---- 7. 敏感性 ----
    story.append(Paragraph("7. 敏感性分析", st["h1"]))
    temp = sens.get("temp") if isinstance(sens, dict) else None
    if isinstance(sens, dict) and sens.get("temp"):
        temp = sens["temp"]
        story.append(Paragraph(temp.get("conclusion", ""), st["body"]))
        story.append(Spacer(1, 2 * mm))
        pts = temp.get("points", [])
        if pts:
            rows = [["温度档位", "MTBF (h)", "λ_total (FIT)"]]
            for p in pts:
                rows.append([p["label"], _fmt(p["mtbf_hours"], 0), _fmt(p["lambda_total_fit"], 3)])
            story.append(_tbl(rows, widths=[50 * mm, 50 * mm, 50 * mm]))
        rank = sens.get("ranking") or []
        if rank:
            story.append(Spacer(1, 3 * mm))
            story.append(Paragraph("各假设影响幅度排序", st["h2"]))
            rows = [["假设", "变化", "MTBF (h)", "变化幅度"]]
            for r in rank:
                rows.append([r["variable"], r["change"], _fmt(r["mtbf"], 0), f'{r["delta_pct"]:.1f}%'])
            story.append(_tbl(rows, widths=[40 * mm, 65 * mm, 40 * mm, 30 * mm]))
    else:
        story.append(Paragraph("本次评估未运行敏感性分析。", st["body"]))

    # ---- 8. 结论与建议 ----
    story.append(PageBreak())
    story.append(Paragraph("8. 综合结论与改进建议", st["h1"]))
    story.append(Paragraph(f'综合判定：<b>{verdict}</b>。' + (a.get("verdict_reasons") or [""])[0], st["body"]))
    story.append(Spacer(1, 3 * mm))
    for i, s in enumerate(_suggestions(payload), 1):
        story.append(Paragraph(f"{i}. {s}", st["body"]))
        story.append(Spacer(1, 1.5 * mm))

    # ---- 附录 A 计算明细 ----
    story.append(PageBreak())
    story.append(Paragraph("附录 A　计算明细（前 10 个短板零件）", st["h1"]))
    story.append(Paragraph("每个零件的每一步：公式 → 代入值 → 结果 → 依据。可据此逐步核对。", st["small"]))
    story.append(Spacer(1, 2 * mm))
    parts_map = {p["part_id"]: p for p in a.get("parts", [])}
    shown = 0
    for r in a.get("top_contributors", []):
        p = parts_map.get(r["part_id"])
        if not p or not p.get("trace"):
            continue
        shown += 1
        if shown > 10:
            break
        story.append(Paragraph(f'{r["part_number"]}　（{p.get("category_name","")}，用量 {p["qty"]}）', st["h2"]))
        rows = [["步骤", "名称", "公式与代入", "结果"]]
        for s in p["trace"]:
            rows.append([
                s["step"],
                Paragraph(s["name"], st["cell"]),
                Paragraph(str(s["formula"]).replace("\n", "<br/>"), st["cell"]),
                f'{_fmt(s["value"], 5)}{"（默认）" if s.get("is_default") else ""}',
            ])
        story.append(_tbl(rows, widths=[10 * mm, 30 * mm, 92 * mm, 28 * mm]))
        story.append(Spacer(1, 2.5 * mm))

    # ---- 附录 B 参数来源 ----
    story.append(Paragraph("附录 B　参数来源与版本", st["h1"]))
    story.append(
        _tbl(
            [
                ["项目", "内容"],
                ["计算标准", param_meta.get("display_name", "")],
                ["参数版本", a.get("param_version", "")],
                ["引擎版本", a.get("engine_version", "")],
                ["标准依据", param_meta.get("source_ref", "")],
                ["磨损模型", load_wear_models(str(settings.param_dir)).get("source_ref", "")],
                ["降额准则", load_derating_rules(str(settings.param_dir)).get("source_ref", "")],
            ],
            widths=[30 * mm, 130 * mm],
        )
    )

    # ---- 附录 C 免责 ----
    story.append(Paragraph("附录 C　免责声明与口径说明", st["h1"]))
    for line in [
        "1. 本报告为理论可靠性预计，反映随机失效视角，精度通常为 ±2~5 倍，不代表实测寿命或现场故障率。",
        "2. 预计结果不能替代 RDT（可靠性增长/验证试验）或现场数据；对外承诺前必须取得实测证据。",
        "3. 磨损寿命部分为工程近似模型，输入（额定寿命、动作频次）以 BOM 描述解析或人工补录为准，缺数据时采用保守默认值。",
        "4. 参数库为示例数据（来源已在附录 B 标注），仅用于演示与学习，不得用于产品认证。",
        "5. 冗余收益未计入共因失效影响，实际收益通常低于计算值。",
        "6. MTBF 与「产品能用 N 年」不等价：本报告不提供寿命承诺，只提供随机失效视角的存活率与磨损视角的估算。",
    ]:
        story.append(Paragraph(line, st["body"]))

    return story


def _page_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(CN_FONT, 7.5)
    canvas.setFillColor(colors.HexColor("#888888"))
    canvas.drawString(18 * mm, 10 * mm, "电子零件可靠性评估系统 · 示例数据，仅供演示/学习")
    canvas.drawRightString(192 * mm, 10 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def build_pdf(project: Dict[str, Any], payload: Dict[str, Any], param_meta: Dict[str, Any], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="电子零件可靠性评估报告",
        author="电子零件可靠性评估系统",
    )
    story = _build_story(project, payload, param_meta, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return out_path


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------


def _sheet(wb: Workbook, title: str, headers: List[str], rows: List[List[Any]], widths: Optional[List[int]] = None):
    ws = wb.create_sheet(title)
    ws.append(headers)
    head_fill = PatternFill("solid", fgColor="1F3864")
    thin = Side(style="thin", color="BFC9D9")
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF", name="微软雅黑", size=10)
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths or [], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="微软雅黑", size=9)
            cell.border = Border(bottom=thin)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    return ws


def build_xlsx(project: Dict[str, Any], payload: Dict[str, Any], param_meta: Dict[str, Any], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    a = payload.get("assessment", {})
    wear = payload.get("wear", {}) or {}
    der = payload.get("derating", {}) or {}
    sens = payload.get("sensitivity", {}) or {}

    wb = Workbook()
    wb.remove(wb.active)

    # 汇总
    ws = wb.create_sheet("汇总")
    rows = [
        ["项目名称", project.get("name", "")],
        ["项目编号", project.get("code", "")],
        ["BOM 版本", project.get("bom_label", "")],
        ["计算标准", param_meta.get("display_name", "")],
        ["参数版本", a.get("param_version", "")],
        ["引擎版本", a.get("engine_version", "")],
        ["计算模式", a.get("mode", "")],
        ["环境类别", (payload.get("assumptions") or {}).get("environment", "")],
        ["环境温度 °C", (payload.get("assumptions") or {}).get("ambient_temp_c", "")],
        ["质量等级", (payload.get("assumptions") or {}).get("quality_level", "")],
        ["日通电小时", (payload.get("assumptions") or {}).get("duty_hours_per_day", "")],
        ["λ_total (FIT)", a.get("lambda_total_fit")],
        ["MTBF (h)", a.get("mtbf_hours")],
        ["R(t) 目标年限", a.get("r_at_target")],
        ["判定", a.get("verdict")],
        ["生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
    ]
    ws.append(["项目", "内容"])
    for r in rows:
        ws.append(r)
    for c in range(1, 3):
        ws.cell(row=1, column=c).font = Font(bold=True, color="FFFFFF", name="微软雅黑")
        ws.cell(row=1, column=c).fill = head_fill_factory()
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 60

    # 假设
    _sheet(wb, "假设参数", ["参数", "取值", "说明"], [r[1:] if len(r) == 3 else r for r in _assumption_lines(payload, param_meta)][1:], [28, 46, 50])

    # 计算明细
    calc_rows = []
    for p in a.get("parts", []):
        calc_rows.append([
            p["part_number"], p.get("category_name", ""), p["qty"], p["lambda_b"],
            json.dumps(p.get("factors", {}), ensure_ascii=False), p["lambda_part"],
        ])
    _sheet(wb, "计算明细", ["料号", "类别", "用量", "λ_b (FIT)", "因子", "λ_零件 (FIT)"], calc_rows, [26, 26, 8, 12, 46, 16])

    # 短板
    _sheet(
        wb, "短板排序", ["排名", "料号", "类别", "用量", "λ (FIT)", "占比 %", "累计 %"],
        [[i, r["part_number"], r.get("category_name", ""), r["qty"], r["lambda_part"], r["contribution_pct"], r.get("cumulative_pct")]
         for i, r in enumerate(a.get("top_contributors", []), 1)],
        [8, 26, 26, 8, 14, 12, 12],
    )

    # 磨损
    _sheet(
        wb, "磨损寿命", ["料号", "机理", "寿命 (h)", "折算年限", "是否限制项", "计算式", "默认值项"],
        [[w["part_number"], w["mechanism_label"], w["life_hours"], w["life_years"], "是" if w.get("is_limiting") else "",
          w["formula"], "；".join(w.get("using_defaults", []))] for w in wear.get("items", [])],
        [26, 26, 14, 12, 12, 60, 40],
    )

    # 降额
    _sheet(
        wb, "降额检查", ["料号", "应力类型", "额定值", "工作值", "比值", "规范上限", "判定", "说明"],
        [[d["part_number"], d["stress_type"], d["rated_value"], d["applied_value"],
          d["ratio"], d["max_ratio"],
          {"pass": "满足", "marginal": "接近", "violation": "超限", "no_data": "缺数据"}.get(d["verdict"], d["verdict"]),
          d["note"]] for d in der.get("items", [])],
        [26, 12, 12, 12, 10, 12, 10, 70],
    )

    # 敏感性
    temp = (sens or {}).get("temp") if isinstance(sens, dict) else None
    if temp:
        _sheet(wb, "敏感性", ["温度档位", "MTBF (h)", "λ_total (FIT)"],
               [[p["label"], p["mtbf_hours"], p["lambda_total_fit"]] for p in temp.get("points", [])], [16, 18, 18])

    # 结论
    _sheet(wb, "结论与建议", ["序号", "建议"], [[i, s] for i, s in enumerate(_suggestions(payload), 1)], [8, 120])

    wb.save(str(out_path))
    return out_path


def head_fill_factory():
    return PatternFill("solid", fgColor="1F3864")


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------


def generate(
    db,
    record,
    kind: str = "pdf",
    extra: Optional[Dict[str, Any]] = None,
    include_dual: bool = True,
) -> Path:
    """生成报告文件，返回路径。

    extra 里可传 project / payload / param_meta，避免重复查询；
    不传则从数据库按 record 重新装配（历史报告重下时走这条路）。
    """
    from ..models import BomVersion, Project
    from ..services import assess as assess_service
    from ..services import bom as bom_service

    project = db.get(Project, record.project_id)
    version = db.get(BomVersion, record.bom_version_id)
    payload = (extra or {}).get("payload") or assess_service.load_result(db, record)
    param_meta = assess_service.param_meta(record.standard)

    if include_dual:
        try:
            from core.models import Assumption

            assumption = assess_service.to_core_assumption(assess_service._assumption_of(record))
            parts = bom_service.items_to_part_inputs(db, version.id)
            payload["dual_standard"] = core_compare(parts, assumption, str(settings.param_dir))
        except Exception:
            payload["dual_standard"] = {}

    proj_ctx = {
        "name": project.name if project else "",
        "code": project.code if project else "",
        "bom_label": f"v{version.version_no} · {version.label}" if version else "",
        "row_count": version.row_count if version else 0,
        "qty_total": version.qty_total if version else 0,
        "target_years": proj_target(project, "target_years", 5),
        "target_survival": proj_target(project, "target_survival", 0.95),
    }

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"report_{project.code if project else 'proj'}_a{record.id}_{stamp}"
    out = (settings.report_dir / f"{name}.{kind}").resolve()

    if kind == "pdf":
        return build_pdf(proj_ctx, payload, param_meta, out)
    return build_xlsx(proj_ctx, payload, param_meta, out)


def proj_target(project, attr: str, default):
    try:
        v = getattr(project, attr, default)
        return v if v is not None else default
    except Exception:
        return default
