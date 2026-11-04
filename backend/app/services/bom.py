"""
app/services/bom.py — BOM 模板、上传解析、入库与转换

【这个模块做什么】
1. 生成/下载 BOM 模板（Excel）；
2. 解析上传的 Excel/CSV，做字段校验并返回问题清单；
3. 把解析结果或模拟数据写进 bom_versions / bom_items；
4. 把数据库里的行转换成计算核心需要的 PartInput。

【为什么自己做解析而不引 pandas】
pandas 能省代码，但会把"0.1uF"这类文本自动转成数字 0.1，把前后导零、日期格式也一起改掉，
反而给"从描述里解析额定值"埋坑。openpyxl 读原始单元格值（data_only=True），
拿到什么就是什么，文本处理交给 core.parse_spec，可控性更好。

【校验分级】
  error：缺必需列、某行缺料号/描述、用量非法且无法兜底 → 该行不入库（或整表拒绝）
  warn ：重复料号、描述过短、用量为空（按 1 处理）→ 入库但提示
这样用户既能看见问题，又不会因为一条脏数据整份 BOM 都导不进来。
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy.orm import Session

from core.models import PartInput

from ..models import BomItem, BomParseIssue, BomVersion

TEMPLATE_HEADERS = ["料号 (必填)", "规格描述 (必填)", "用量 (必填)", "位号", "备注"]
TEMPLATE_SAMPLE = [
    ["SIM-CAP-ALU-470U35", "CAP ALU 470uF 35V 105℃ 2000h φ10×12", 3, "C1,C2,C3", "示例行，可删除"],
    ["SIM-RES-10K-0603", "RES 10KΩ 1% 1/10W 0603 厚膜", 24, "R1-R24", ""],
    ["SIM-IC-STM32F103", "IC MCU STM32F103C8T6 LQFP-48 72MHz", 1, "U1", ""],
]

# 表头识别：容忍中英文、带括号后缀的写法
HEADER_ALIASES = {
    "part_number": ["料号", "part", "p/n", "pn", "编号", "物料编码", "元件编号"],
    "description": ["规格描述", "描述", "description", "spec", "规格", "型号描述", "名称"],
    "qty": ["用量", "数量", "qty", "quantity", "单机用量"],
    "ref_des": ["位号", "ref", "designator", "位置号", "reference"],
    "note": ["备注", "note", "remark"],
}


def build_template() -> bytes:
    """生成模板 xlsx（含示例行与填表说明）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws.append(TEMPLATE_HEADERS)
    for c in range(1, len(TEMPLATE_HEADERS) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="3A6EA5")
        cell.alignment = Alignment(horizontal="center")
    for row in TEMPLATE_SAMPLE:
        ws.append(row)

    widths = [26, 46, 12, 22, 24]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w

    guide = wb.create_sheet("填表说明")
    for line in [
        ["字段", "是否必填", "说明"],
        ["料号", "必填", "零件唯一编号，重复料号会被提示（不阻断导入）"],
        ["规格描述", "必填", "尽量写全：类型 + 容值/阻值 + 耐压 + 封装 + 温度/寿命。系统靠它自动分类与解析额定值"],
        ["用量", "必填", "整数，单机使用数量"],
        ["位号", "可选", "如 C1,C2 或 R1-R24，便于核对"],
        ["备注", "可选", ""],
        ["", "", ""],
        ["提示", "", "描述写得越标准，自动分类越准。若某行被判为「未识别」，可在系统里人工指定分类。"],
    ]:
        guide.append(line)
    guide.column_dimensions["A"].width = 16
    guide.column_dimensions["B"].width = 12
    guide.column_dimensions["C"].width = 90

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _map_headers(row: List[Any]) -> Dict[str, int]:
    """把表头行映射成 {字段: 列索引}。"""
    mapping: Dict[str, int] = {}
    for idx, cell in enumerate(row):
        text = str(cell or "").strip().lower()
        text = re.sub(r"[（(].*?[)）]", "", text).strip()
        if not text:
            continue
        for field, aliases in HEADER_ALIASES.items():
            if field in mapping:
                continue
            if any(a in text for a in aliases):
                mapping[field] = idx
                break
    return mapping


def _read_rows(filename: str, content: bytes) -> List[List[Any]]:
    if filename.lower().endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return [row for row in csv.reader(io.StringIO(text))]
    wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    ws = wb.active
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


def parse_upload(filename: str, content: bytes) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """解析上传文件 → (行列表, 问题列表)。问题列表里 level=error 的行不返回。"""
    rows = _read_rows(filename, content)
    if not rows:
        return [], [{"level": "error", "code": "empty_file", "message": "文件为空或无法读取", "line_no": None}]

    # 找到表头行：前 10 行里第一个能识别出"料号"和"描述"的行
    header_idx = -1
    mapping: Dict[str, int] = {}
    for i, row in enumerate(rows[:10]):
        m = _map_headers(row)
        if "part_number" in m and "description" in m:
            header_idx, mapping = i, m
            break

    issues: List[Dict[str, Any]] = []
    if header_idx < 0:
        return [], [
            {
                "level": "error",
                "code": "missing_column",
                "message": "未找到表头行。请确认表格含「料号」与「规格描述」两列（可下载模板对照）",
                "line_no": None,
            }
        ]

    for required, label in [("part_number", "料号"), ("description", "规格描述")]:
        if required not in mapping:
            issues.append(
                {
                    "level": "error",
                    "code": "missing_column",
                    "message": f"缺少必需列：{label}",
                    "line_no": header_idx + 1,
                }
            )
    if "qty" not in mapping:
        issues.append(
            {
                "level": "warn",
                "code": "missing_qty_column",
                "message": "缺少「用量」列，所有行将按用量 1 处理",
                "line_no": header_idx + 1,
            }
        )
    if any(i["level"] == "error" for i in issues):
        return [], issues

    parsed: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}

    for r_i, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
        if not any(str(c or "").strip() for c in row):
            continue

        def cell(field: str) -> str:
            idx = mapping.get(field)
            if idx is None or idx >= len(row):
                return ""
            return str(row[idx] if row[idx] is not None else "").strip()

        pn = cell("part_number")
        desc = cell("description")
        qty_raw = cell("qty")

        if not pn and not desc:
            continue
        if not pn:
            issues.append(
                {"level": "warn", "code": "missing_pn", "message": f"第 {r_i} 行缺料号，已用「UNKNOWN-L{r_i}」占位", "line_no": r_i}
            )
            pn = f"UNKNOWN-L{r_i}"
        if not desc:
            issues.append(
                {"level": "error", "code": "missing_desc", "message": f"第 {r_i} 行缺规格描述，已跳过", "line_no": r_i}
            )
            continue
        if len(desc) < 3:
            issues.append(
                {"level": "warn", "code": "desc_too_short", "message": f"第 {r_i} 行描述过短（「{desc}」），自动分类可能失败", "line_no": r_i}
            )

        qty = 1
        if qty_raw:
            try:
                qty = int(float(qty_raw))
                if qty <= 0:
                    raise ValueError
            except ValueError:
                issues.append(
                    {"level": "warn", "code": "qty_invalid", "message": f"第 {r_i} 行用量「{qty_raw}」非法，已按 1 处理", "line_no": r_i}
                )
                qty = 1
        else:
            issues.append(
                {"level": "warn", "code": "qty_empty", "message": f"第 {r_i} 行用量为空，已按 1 处理", "line_no": r_i}
            )

        if pn in seen:
            issues.append(
                {
                    "level": "warn",
                    "code": "dup_pn",
                    "message": f"第 {r_i} 行料号「{pn}」与第 {seen[pn]} 行重复（可能是同一料号分多行写，不影响计算，但建议合并）",
                    "line_no": r_i,
                }
            )
        else:
            seen[pn] = r_i

        parsed.append(
            {
                "line_no": r_i,
                "part_number": pn,
                "description": desc,
                "qty": qty,
                "ref_des": cell("ref_des"),
                "suggested_stress": {},
                "suggested_rated": {},
            }
        )

    if not parsed and not issues:
        issues.append({"level": "error", "code": "no_data_row", "message": "表格中没有有效数据行", "line_no": None})

    return parsed, issues


def create_version(
    db: Session,
    project_id: int,
    label: str,
    source: str,
    filename: str,
    rows: List[Dict[str, Any]],
    issues: List[Dict[str, Any]],
    user_id: Optional[int],
) -> BomVersion:
    """建一份 BOM 版本并写入行数据。"""
    last_no = (
        db.query(BomVersion)
        .filter(BomVersion.project_id == project_id)
        .order_by(BomVersion.version_no.desc())
        .first()
    )
    version = BomVersion(
        project_id=project_id,
        version_no=(last_no.version_no + 1) if last_no else 1,
        label=label,
        source=source,
        filename=filename,
        row_count=len(rows),
        qty_total=sum(int(r.get("qty") or 0) for r in rows),
        parse_warnings_json=json.dumps(issues, ensure_ascii=False),
        uploaded_by=user_id,
    )
    db.add(version)
    db.flush()

    for r in rows:
        db.add(
            BomItem(
                bom_version_id=version.id,
                line_no=int(r.get("line_no") or 0),
                part_number=str(r.get("part_number") or ""),
                description=str(r.get("description") or ""),
                qty=int(r.get("qty") or 1),
                ref_des=str(r.get("ref_des") or ""),
                rated_json=json.dumps(r.get("suggested_rated") or {}, ensure_ascii=False),
                rated_source="simulated" if r.get("suggested_rated") else "",
                stress_json=json.dumps(r.get("suggested_stress") or {}, ensure_ascii=False),
                match_status="unclassified",
            )
        )

    for i in issues:
        db.add(
            BomParseIssue(
                bom_version_id=version.id,
                level=i.get("level", "warn"),
                code=i.get("code", ""),
                message=i.get("message", ""),
                line_no=i.get("line_no"),
            )
        )

    db.commit()
    return version


def items_to_part_inputs(db: Session, version_id: int) -> List[PartInput]:
    """数据库行 → 计算核心的 PartInput 列表。

    这里做三件事，缺一个结果就会错：
      1. category_id → category_code（引擎认 code，不认自增 id）
      2. rated/stress 的 JSON 反序列化
      3. 未分类的行【直接报错】，绝不静默跳过（跳过会让 MTBF 虚高）
    """
    rows = (
        db.query(BomItem)
        .filter(BomItem.bom_version_id == version_id)
        .order_by(BomItem.line_no, BomItem.id)
        .all()
    )
    cat_code = {}
    from ..models import Category

    for c in db.query(Category).all():
        cat_code[c.id] = c.code

    parts: List[PartInput] = []
    unclassified = []
    for r in rows:
        code = cat_code.get(r.category_id or -1, "")
        if not code:
            unclassified.append(f"{r.part_number}（{r.description[:24]}）")
            continue
        parts.append(
            PartInput(
                part_id=r.id,
                part_number=r.part_number,
                description=r.description,
                qty=max(1, r.qty),
                category_code=code,
                stress=_loads(r.stress_json),
                rated=_loads(r.rated_json),
                redundancy_group=r.redundancy_group,
                redundancy_note=r.redundancy_note,
            )
        )

    if unclassified:
        raise ValueError(
            f"还有 {len(unclassified)} 行未完成分类，无法评估。例如："
            + "；".join(unclassified[:3])
            + ("……" if len(unclassified) > 3 else "")
        )
    return parts


def _loads(text: str) -> Dict[str, Any]:
    try:
        v = json.loads(text or "{}")
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}
