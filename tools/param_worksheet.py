"""
tools/param_worksheet.py — 参数库录入工单：导出 Excel、填完回写

【解决什么问题】
系统里的 λ_b / λ_G 目前是公开文献的典型量级，不是标准原表的值。要变成"可以对外
引用的数字"，只能有人拿着标准正本，把表一格一格录进去。这一步绕不过去，但可以
把它做得不容易出错：

    导出工单 → 填「录入值」列 → 回写（自动校验 + 自动备份 + 自动改数据成色）

【为什么不做成界面里点几下就改】
录表是低频、高精度、需要两个人交叉核对的活。Excel 适合这个场景：能打印、能传阅、
能留手写批注、能被另一个人复核。界面适合高频操作，不适合一次性录 200 个数。

【怎么用】
    # 1. 导出待填工单
    python tools/param_worksheet.py export --standard MIL-217F

    # 2. 用 Excel 打开 docs/参数录入工单_MIL-217F.xlsx，只在「录入值」列填数
    #    （留空 = 不动，仍然用系统当前值）

    # 3. 先校验，不改文件
    python tools/param_worksheet.py import --standard MIL-217F --file docs/参数录入工单_MIL-217F.xlsx

    # 4. 校验通过后写回
    python tools/param_worksheet.py import --standard MIL-217F --file docs/参数录入工单_MIL-217F.xlsx --apply

【回写后会怎样】
    - 原 JSON 自动备份为 xxx.json.bak（同目录，可回退）
    - data_quality 按覆盖率自动改：全填 = verified，填了一部分 = partial，一个没填 = 不动
    - 重新跑一次评估即可看到新数字；历史报告的存档数字不受影响（结果快照）
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Any, Dict, List, Optional, Tuple

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

PARAM_DIR = os.path.join(BACKEND, "params")
FILES = {
    "MIL-217F": "mil217f_v1.json",
    "TELCORDIA_SR332": "telcordia_sr332_v1.json",
}

# 分组 → 标准里的章节名。只写章节「名称」不写编号：
# 编号在不同 Notice / Issue 之间会挪，写错了反而误导，让填表人按名字在 PDF 里找更稳。
SECTION_BY_GROUP = {
    "集成电路": "集成电路",
    "IC": "集成电路",
    "二极管": "分立半导体",
    "晶体管": "分立半导体",
    "LED": "分立半导体",
    "电阻": "电阻",
    "电容": "电容",
    "电感": "电感与变压器",
    "继电器": "继电器",
    "开关": "开关",
    "连接器": "连接器",
    "晶振": "石英晶体",
    "保险丝": "保险丝",
    "机电件": "机电件（按子类：风扇→旋转器件 / PCB→印制板 / 焊点→焊接点）",
    "模组": "标准未覆盖（217F/SR-332 无电源模组模型）",
    "结构五金件": "标准未覆盖（机械件，见 NSWC-11）",
    "线缆线束": "标准未覆盖（见 NPRD）",
    "导热辅料": "标准未覆盖",
    "包装标识": "标准未覆盖",
}

# 机电件三类各自的章节，避免一个笼统的"机电件"让人无从下手
SECTION_BY_CODE = {
    "FAN": "旋转器件",
    "PCB": "印制板",
    "SOLDER": "焊接点",
    "MODULE_POWER": "标准未覆盖",
}

SHEET_NOTE = "怎么填"
SHEET_LAMBDA = "1-λ基础失效率"
SHEET_ENV = "2-环境因子（π_E）"
SHEET_QUAL = "3-质量因子（π_Q）"
SHEET_TEMP = "4-温度因子（π_T）"


# ---------------------------------------------------------------------------
# 公共
# ---------------------------------------------------------------------------


def _load(standard: str) -> Tuple[str, Dict[str, Any]]:
    path = os.path.join(PARAM_DIR, FILES[standard])
    with open(path, "r", encoding="utf-8") as f:
        return path, json.load(f)


def _detect_indent(path: str) -> int:
    """沿用原文件的缩进宽度，避免回写后整个文件 diff 爆炸。"""
    with open(path, "r", encoding="utf-8") as f:
        for line in f.readlines()[1:6]:
            stripped = line.lstrip(" ")
            if stripped and len(line) > len(stripped):
                return len(line) - len(stripped)
    return 2


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    text = str(v).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def export(standard: str, out: str) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    _, raw = _load(standard)
    wb = Workbook()
    wb.remove(wb.active)

    head_fill = PatternFill("solid", fgColor="1F3864")
    fill_fill = PatternFill("solid", fgColor="FFF2CC")  # 要填的列用浅黄底，一眼能看出哪里该动手
    thin = Side(style="thin", color="BFC9D9")

    def sheet(title: str, headers: List[str], rows: List[List[Any]], widths: List[int], fill_col: int):
        ws = wb.create_sheet(title)
        ws.append(headers)
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=c)
            cell.font = Font(bold=True, color="FFFFFF", name="微软雅黑", size=10)
            cell.fill = head_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for r in rows:
            ws.append(r)
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.font = Font(name="微软雅黑", size=9)
                cell.border = Border(bottom=thin)
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                if cell.column == fill_col:
                    cell.fill = fill_fill
        ws.freeze_panes = "A2"
        return ws

    # --- Sheet 0：说明 ---
    ws = wb.create_sheet(SHEET_NOTE)
    notes = [
        ["参数录入工单", ""],
        ["适用标准", raw.get("display_name", standard)],
        ["标准依据", raw.get("source_ref", "")],
        ["", ""],
        ["填表规则（只有一条）", "只在浅黄色的「录入值」列填数；留空表示不动，系统继续用当前值。"],
        ["单位", "失效率一律填 FIT（每 10 亿小时的失效次数）。标准原文若给的是 failures/10^6 h，需要 ×1000。"],
        ["小数", "按原表精度填，不要四舍五入到整数——差一个数量级比不填更危险。"],
        ["核对", "建议两个人分别填一份，用第 3 方对比；本工具校验的是「格式与量级」，判断不了「抄错行」。"],
        ["", ""],
        ["填完做什么", "先跑 import 不带 --apply 校验，通过后再加 --apply 写回；写回会自动备份原 JSON。"],
        ["", ""],
        ["注意", "页面上的「数据成色」会随覆盖率自动变化：全填 = 已按标准原表录入，填一部分 = 部分类目已录入。"],
        ["注意", "历史评估的数字不会变——它们存在结果快照里，改参数只影响之后新跑的评估。"],
    ]
    for r in notes:
        ws.append(r)
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 100
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=ws.max_row), start=1):
        row[0].font = Font(name="微软雅黑", size=10, bold=(i == 1))
        row[0].alignment = Alignment(vertical="top", wrap_text=True)
        row[1].alignment = Alignment(vertical="top", wrap_text=True)
        if i == 1:
            row[0].font = Font(name="微软雅黑", size=14, bold=True)

    # --- Sheet 1：λ ---
    cats = raw.get("categories", {})
    rows = []
    for code, spec in cats.items():
        group = spec.get("group", "")
        section = SECTION_BY_CODE.get(code) or SECTION_BY_GROUP.get(group, group)
        covered = "否" if section.startswith("标准未覆盖") else "是"
        rows.append([
            code,
            spec.get("name", ""),
            group,
            section,
            covered,
            spec.get("lambda_g"),
            None,
            "FIT",
            "",
        ])
    sheet(
        SHEET_LAMBDA,
        ["类目编码", "类目名称", "分组", "标准章节（按名称找）", "标准覆盖", "当前值", "录入值", "单位", "备注"],
        rows,
        [22, 24, 12, 40, 10, 10, 10, 8, 30],
        fill_col=7,
    )

    # --- Sheet 2：π_E ---
    rows = []
    for code, spec in (raw.get("environments") or {}).items():
        rows.append([code, spec.get("label", ""), spec.get("mult"), None, "倍率", ""])
    sheet(SHEET_ENV, ["环境编码", "说明", "当前值", "录入值", "单位", "备注"], rows, [12, 40, 10, 10, 8, 34], fill_col=4)

    # --- Sheet 3：π_Q ---
    rows = []
    for code, spec in (raw.get("quality_levels") or {}).items():
        rows.append([code, spec.get("label", ""), spec.get("pi_q"), None, "倍率", ""])
    sheet(SHEET_QUAL, ["质量档位", "说明", "当前值", "录入值", "单位", "备注"], rows, [14, 40, 10, 10, 8, 34], fill_col=4)

    # --- Sheet 4：π_T ---
    families = raw.get("families") or {}
    rows = []
    for code, spec in cats.items():
        fam = families.get(spec.get("family", ""), {})
        ts = (spec.get("parts_stress") or {}).get("pi_T") or ((fam.get("parts_stress") or {}).get("pi_T")) or {}
        inherited = "继承族模板" if not (spec.get("parts_stress") or {}).get("pi_T") else "类目自有"
        rows.append([
            code,
            spec.get("name", ""),
            ts.get("formula", "power_law"),
            ts.get("ref_temp_c"),
            ts.get("exponent"),
            ts.get("ea_ev"),
            ts.get("default_delta_t_c") or (fam.get("parts_stress") or {}).get("default_delta_t_c"),
            inherited,
            None,
            None,
            None,
            None,
        ])
    sheet(
        SHEET_TEMP,
        ["类目编码", "类目名称", "公式形式", "参考温度 °C", "幂指数 n", "活化能 Ea (eV)",
         "默认温升 °C", "来源", "录入 参考温度", "录入 幂指数/Ea", "录入 默认温升", "备注"],
        rows,
        [20, 22, 14, 12, 10, 12, 12, 14, 12, 14, 12, 24],
        fill_col=9,
    )

    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    wb.save(out)
    return out


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


def _read_sheet(path: str, title: str) -> List[Dict[str, Any]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    if title not in wb.sheetnames:
        raise SystemExit(f"工单里缺少工作表「{title}」，请用 export 重新生成")
    ws = wb[title]
    headers = [str(c.value or "").strip() for c in ws[1]]
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not any(v not in (None, "") for v in row):
            continue
        out.append(dict(zip(headers, row)))
    return out


def _validate_lambda(value: float, code: str) -> Optional[str]:
    if value <= 0:
        return f"{code}: 失效率必须 > 0（填的是 {value}）"
    if value > 1e6:
        return f"{code}: {value} FIT 明显过大，检查是否漏了单位换算（failures/10^6h → FIT 要 ×1000）"
    if value < 1e-6:
        return f"{code}: {value} FIT 过小（低于 1e-6），检查小数点位置"
    return None


def _validate_sorted(pairs: List[Tuple[str, float]], label: str) -> List[str]:
    """环境/质量因子应当单调，抄错行最常见的形态就是"两个值换了位置"。"""
    errs = []
    vals = [v for _, v in pairs]
    if vals and vals != sorted(vals):
        errs.append(f"{label} 不单调（当前录入顺序为 {vals}），很可能是抄错行，请核对")
    return errs


def do_import(standard: str, path: str, apply: bool) -> int:
    jpath, raw = _load(standard)

    lam_rows = _read_sheet(path, SHEET_LAMBDA)
    env_rows = _read_sheet(path, SHEET_ENV)
    qual_rows = _read_sheet(path, SHEET_QUAL)
    temp_rows = _read_sheet(path, SHEET_TEMP)

    errors: List[str] = []
    changes: List[str] = []

    # ---- λ ----
    cats = raw.setdefault("categories", {})
    lam_filled = lam_total = 0
    for r in lam_rows:
        code = str(r.get("类目编码") or "").strip()
        if not code or code not in cats:
            continue
        if str(r.get("标准覆盖") or "").strip() == "是":
            lam_total += 1
        val = _num(r.get("录入值"))
        if val is None:
            continue
        lam_filled += 1
        err = _validate_lambda(val, code)
        if err:
            errors.append(err)
            continue
        old = cats[code].get("lambda_g")
        if old != val:
            changes.append(f"λ_b {code}: {old} → {val}")
            if apply:
                cats[code]["lambda_g"] = val

    # ---- π_E ----
    envs = raw.setdefault("environments", {})
    env_filled = env_total = 0
    env_vals: List[Tuple[str, float]] = []
    for r in env_rows:
        code = str(r.get("环境编码") or "").strip()
        if not code or code not in envs:
            continue
        env_total += 1
        val = _num(r.get("录入值"))
        if val is None:
            continue
        env_filled += 1
        if val <= 0:
            errors.append(f"π_E {code}: 倍率必须 > 0")
            continue
        env_vals.append((code, val))
        old = envs[code].get("mult")
        if old != val:
            changes.append(f"π_E {code}: {old} → {val}")
            if apply:
                envs[code]["mult"] = val
    if env_vals:
        errors.extend(_validate_sorted(env_vals, "π_E 环境因子"))

    # ---- π_Q ----
    quals = raw.setdefault("quality_levels", {})
    qual_filled = qual_total = 0
    qual_vals: List[Tuple[str, float]] = []
    for r in qual_rows:
        code = str(r.get("质量档位") or "").strip()
        if not code or code not in quals:
            continue
        qual_total += 1
        val = _num(r.get("录入值"))
        if val is None:
            continue
        qual_filled += 1
        if val <= 0:
            errors.append(f"π_Q {code}: 倍率必须 > 0")
            continue
        qual_vals.append((code, val))
        old = quals[code].get("pi_q")
        if old != val:
            changes.append(f"π_Q {code}: {old} → {val}")
            if apply:
                quals[code]["pi_q"] = val
    if qual_vals:
        errors.extend(_validate_sorted(qual_vals, "π_Q 质量因子"))

    # ---- π_T ----
    temp_filled = temp_total = 0
    for r in temp_rows:
        code = str(r.get("类目编码") or "").strip()
        if not code or code not in cats:
            continue
        temp_total += 1
        ref = _num(r.get("录入 参考温度"))
        expo = _num(r.get("录入 幂指数/Ea"))
        dlt = _num(r.get("录入 默认温升"))
        if ref is None and expo is None and dlt is None:
            continue
        temp_filled += 1
        spec = cats[code].setdefault("parts_stress", {})
        pi_t = spec.setdefault("pi_T", {})
        if not pi_t:
            # 类目原本继承族模板：把模板抄过来再改，避免回写后丢字段
            fam = (raw.get("families") or {}).get(cats[code].get("family", ""), {})
            tmpl = (fam.get("parts_stress") or {}).get("pi_T") or {}
            pi_t.update(tmpl)
            spec["pi_T"] = pi_t
        formula = str(r.get("公式形式") or pi_t.get("formula") or "power_law").strip()
        pi_t["formula"] = formula
        if ref is not None:
            if ref <= -273:
                errors.append(f"π_T {code}: 参考温度不合理（{ref}°C）")
            else:
                changes.append(f"π_T {code} ref_temp_c: {pi_t.get('ref_temp_c')} → {ref}")
                if apply:
                    pi_t["ref_temp_c"] = ref
        if expo is not None:
            key = "ea_ev" if formula == "arrhenius" else "exponent"
            changes.append(f"π_T {code} {key}: {pi_t.get(key)} → {expo}")
            if apply:
                pi_t[key] = expo
        if dlt is not None:
            changes.append(f"π_T {code} default_delta_t_c: {spec.get('default_delta_t_c')} → {dlt}")
            if apply:
                spec["default_delta_t_c"] = dlt

    # ---- 覆盖率 → 数据成色 ----
    filled = lam_filled + env_filled + qual_filled + temp_filled
    total = lam_total + env_total + qual_total + temp_total
    ratio = (filled / total) if total else 0.0
    new_quality = "verified" if ratio >= 0.999 else ("partial" if filled else raw.get("data_quality", "demo"))

    print(f"工单：{os.path.basename(path)}")
    print(f"覆盖率：{filled}/{total} = {ratio:.0%}（λ {lam_filled}/{lam_total}，"
          f"π_E {env_filled}/{env_total}，π_Q {qual_filled}/{qual_total}，π_T {temp_filled}/{temp_total}）")
    print(f"数据成色：{raw.get('data_quality')} → {new_quality}")

    if errors:
        print(f"\n校验未通过（{len(errors)} 项），未写入：")
        for e in errors[:30]:
            print("  ×", e)
        return 2

    if not changes:
        print("\n没有检测到改动。")
        return 0

    print(f"\n待写入改动 {len(changes)} 项：")
    for c in changes[:40]:
        print("  ·", c)
    if len(changes) > 40:
        print(f"  … 另有 {len(changes) - 40} 项")

    if not apply:
        print("\n仅校验模式（未写入）。确认无误后加 --apply 写回。")
        return 0

    if raw.get("data_quality") != new_quality:
        raw["data_quality"] = new_quality
    indent = _detect_indent(jpath)
    shutil.copyfile(jpath, jpath + ".bak")
    with open(jpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(raw, f, ensure_ascii=False, indent=indent)
        f.write("\n")
    print(f"\n已写入 {jpath}")
    print(f"原文件备份：{jpath}.bak")
    print("下一步：重新跑一次评估，界面上「数据成色」会同步变化。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="参数库录入工单：导出 / 校验 / 回写")
    ap.add_argument("action", choices=["export", "import"])
    ap.add_argument("--standard", default="MIL-217F", choices=list(FILES))
    ap.add_argument("--out", default="", help="export 的输出路径")
    ap.add_argument("--file", default="", help="import 的工单路径")
    ap.add_argument("--apply", action="store_true", help="import 时真正写回（不加则只校验）")
    args = ap.parse_args()

    if args.action == "export":
        name = {"MIL-217F": "MIL-217F", "TELCORDIA_SR332": "SR-332"}.get(args.standard, args.standard)
        out = args.out or os.path.join(
            os.path.dirname(BACKEND), "docs", f"参数录入工单_{name}.xlsx"
        )
        p = export(args.standard, out)
        print(f"已生成：{p}")
        print("用 Excel 打开，只在浅黄色的「录入值」列填数；留空表示沿用系统当前值。")
        return 0

    if not args.file or not os.path.exists(args.file):
        raise SystemExit("请用 --file 指定已填好的工单 xlsx")
    return do_import(args.standard, args.file, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
