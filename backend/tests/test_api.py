"""
tests/test_api.py — 全链路接口测试

【这条测试在验证什么】
它按用户的真实操作顺序走一遍：
    登录 → 看到演示项目 → 查看分类统计 → 处理待确认队列 → 发起评估
         → 查看短板/追溯/磨损/降额/敏感性 → 双标准对比 → 生成并下载报告

单元测试保证"每个公式对"，这条测试保证"串起来能用"。
很多项目单测全绿但流程跑不通，就是因为缺这一层。

注意：报告生成会真的调用 reportlab 与 openpyxl，所以它同时验证了
"中文字体是否注册成功、文件是否真的写出来了"——这是最容易在部署环境翻车的地方。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_login_rejects_bad_password(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_requires_auth(client):
    assert client.get("/api/v1/projects").status_code == 401


def test_demo_project_seeded(client, auth):
    ps = client.get("/api/v1/projects", headers=auth).json()
    assert len(ps) >= 1
    demo = ps[0]
    assert demo["bom_version_count"] == 1
    assert demo["latest_assessment"] is None


def test_classification_stats(client, auth):
    st = client.get("/api/v1/bom/versions/1/stats", headers=auth).json()
    assert st["total"] > 0
    # 演示数据应包含三级分流的全部情形
    assert st["status"]["auto"] > 0
    assert st["status"]["unrecognized"] > 0


def test_queue_and_confirm_then_assess(client, auth):
    vid = 1
    q = client.get(f"/api/v1/bom/versions/{vid}/queue?page_size=100", headers=auth).json()
    assert q["total"] > 0, "演示数据应留下待确认行"

    for item in q["items"]:
        if not item["candidates"]:
            continue
        r = client.post(
            f"/api/v1/bom/items/{item['id']}/confirm",
            json={"category_code": item["candidates"][0]["category_code"], "learn": True},
            headers=auth,
        )
        assert r.status_code == 200, r.text

    st = client.get(f"/api/v1/bom/versions/{vid}/stats", headers=auth).json()
    assert st["pending_total"] == 0

    body = {
        "assumption": {
            "environment": "GB",
            "ambient_temp_c": 55,
            "quality_level": "commercial",
            "duty_hours_per_day": 24,
            "target_years": 5,
            "target_survival": 0.95,
            "standard": "MIL-217F",
            "mode": "parts_stress",
        },
        "with_sensitivity": True,
    }
    r = client.post("/api/v1/projects/1/assess", json=body, headers=auth)
    assert r.status_code == 200, r.text
    data = r.json()
    a = data["assessment"]
    assert a["lambda_total_fit"] > 0
    assert 0 < a["r_at_target"] <= 1
    assert a["verdict"] in ("PASS", "FAIL")

    # 磨损与降额必须都算出来
    assert data["result"]["wear"]["items"], "应有磨损件结果"
    assert data["result"]["derating"]["items"], "应有降额检查结果"
    assert data["result"]["sensitivity"]["temp"]["points"]

    test_queue_and_confirm_then_assess.assessment_id = a["id"]


def test_assessment_details(client, auth):
    aid = getattr(test_queue_and_confirm_then_assess, "assessment_id", None)
    assert aid, "前置用例未生成评估"

    full = client.get(f"/api/v1/assessments/{aid}", headers=auth).json()
    assert full["assessment"]["top_contributors"]
    assert full["meta"]["param_version"]

    items = client.get(f"/api/v1/assessments/{aid}/items?page_size=5", headers=auth).json()
    assert items["total"] > 0

    first = items["items"][0]
    tr = client.get(f"/api/v1/assessments/{aid}/trace/{first['bom_item_id']}", headers=auth).json()
    assert len(tr["trace"]) >= 3
    assert all("formula" in s and "source" in s for s in tr["trace"])

    dual = client.get(f"/api/v1/assessments/{aid}/compare-standards", headers=auth).json()
    assert set(dual["standards"]) == {"MIL-217F", "TELCORDIA_SR332"}
    assert dual["ratio_mil_over_telcordia"] > 0

    sens = client.post(
        f"/api/v1/assessments/{aid}/sensitivity",
        json={"variable": "ambient_temp", "values": [25, 40, 55, 70]},
        headers=auth,
    ).json()
    assert len(sens["points"]) == 4
    mtbfs = [p["mtbf_hours"] for p in sens["points"]]
    assert mtbfs == sorted(mtbfs, reverse=True)


def test_report_pdf_and_xlsx(client, auth):
    aid = getattr(test_queue_and_confirm_then_assess, "assessment_id", None)
    assert aid

    ids = {}
    for kind in ("pdf", "xlsx"):
        r = client.post(f"/api/v1/assessments/{aid}/report", json={"kind": kind}, headers=auth)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["file_size"] > 5000, f"{kind} 文件过小，可能是空文件"
        ids[kind] = body["id"]

    dl = client.get(f"/api/v1/reports/{ids['pdf']}/download", headers=auth)
    assert dl.status_code == 200
    assert dl.content[:4] == b"%PDF", "PDF 文件头不正确"


def test_knowledge_base_editable(client, auth):
    cats = client.get("/api/v1/categories", headers=auth).json()
    assert cats["total"] > 30
    code = cats["tree"][0]["children"][0]["code"]

    r = client.post(
        f"/api/v1/categories/{code}/keywords",
        json={"keyword": "测试关键词XYZ", "weight": 2.0},
        headers=auth,
    )
    assert r.status_code in (201, 400)  # 重复运行时不重复插入

    detail = client.get(f"/api/v1/categories/{code}", headers=auth).json()
    assert any(k["keyword"] == "测试关键词XYZ" for k in detail["keywords"])

    kw_id = [k for k in detail["keywords"] if k["keyword"] == "测试关键词XYZ"][0]["id"]
    assert client.delete(f"/api/v1/keywords/{kw_id}", headers=auth).status_code == 204


def test_bom_template_download(client, auth):
    r = client.get("/api/v1/bom/template.xlsx", headers=auth)
    assert r.status_code == 200
    assert len(r.content) > 3000
    assert r.content[:2] == b"PK"  # xlsx 是 zip 包


def test_glossary_and_params(client, auth):
    g = client.get("/api/v1/glossary", headers=auth).json()
    assert len(g["terms"]) >= 15
    assert all(t.get("plain") for t in g["terms"])

    p = client.get("/api/v1/params/MIL-217F", headers=auth).json()
    assert p["environments"] and p["quality_levels"] and p["categories"]

    versions = client.get("/api/v1/param-versions", headers=auth).json()
    assert len(versions) >= 4


def test_project_survival_percent_is_normalized(client, auth):
    """新建项目按百分数填 95，后端必须存成 0.95。

    这是一个真实踩过的 bug：前端表单按百分数填，后端与计算核心按小数用，
    中间没做转换，存进去就是 95。后果是主页卡片显示「存活率 ≥ 9500%」，
    而评估时把 95 当成目标 R(t)，判定永远不通过——而且这个错不会报任何异常，
    只会让人以为"产品可靠性不够"。
    """
    r = client.post(
        "/api/v1/projects",
        json={"name": "存活率归一化测试", "target_survival": 95},
        headers=auth,
    )
    assert r.status_code in (200, 201), r.text
    assert abs(r.json()["target_survival"] - 0.95) < 1e-9

    # 已经是小数的值不能被二次除
    r2 = client.post(
        "/api/v1/projects",
        json={"name": "存活率小数测试", "target_survival": 0.9},
        headers=auth,
    )
    assert r2.status_code in (200, 201)
    assert abs(r2.json()["target_survival"] - 0.9) < 1e-9

    # 0 / 1 / 负数都是非法目标，必须拦住
    for bad in (0, 1, -5, 150):
        rb = client.post(
            "/api/v1/projects",
            json={"name": f"非法存活率 {bad}", "target_survival": bad},
            headers=auth,
        )
        assert rb.status_code == 422, f"target_survival={bad} 应该被拒绝，实际 {rb.status_code}"


def test_param_meta_exposes_data_quality(client, auth):
    """参数库要自报「数据成色」，否则界面无法区分示例值与照表录入的值。

    没有这个字段，用户在结果页看到 2,348,245 h 时无从判断它是"照标准算的"
    还是"用示例量级估的"——两者在界面上长得一模一样。
    """
    for std in ("MIL-217F", "TELCORDIA_SR332"):
        d = client.get(f"/api/v1/params/{std}", headers=auth)
        assert d.status_code == 200, d.text
        body = d.json()
        assert body.get("data_quality") in ("demo", "partial", "verified"), body.get("data_quality")
        assert body.get("data_quality_note"), "数据成色必须带一句说明，否则用户不知道该怎么改"
        assert body.get("source_ref"), "缺标准出处"


def test_upload_csv_gbk(client, auth):
    """中文 Excel 另存的 CSV 是 GBK，必须能读懂。

    这是 BOM 最常见的来源。只按 UTF-8 解码时整张表变成 \ufffd，
    接着表头识别失败，用户明明有「料号 / 规格描述」两列，却被告诉「未找到表头」——
    提示把矛头指向格式，用户会去改列名，越改越乱。
    """
    csv_text = (
        "料号,规格描述,用量,位号\n"
        "RC0603FR-0710KL,厚膜贴片电阻 10K 1% 0603 50V,12,R1 R2\n"
        "GRM188R71H104KA93D,陶瓷电容 0.1uF 50V 0603 X7R,8,C1 C2\n"
        "GB/T818-M3×8-304,十字盘头螺钉 M3×8 304不锈钢,4,\n"
    )
    content = csv_text.encode("gbk")  # 关键：不用 utf-8

    p = client.post("/api/v1/projects", json={"name": "编码测试 GBK"}, headers=auth)
    assert p.status_code in (200, 201), p.text
    pid = p.json()["id"]

    r = client.post(
        f"/api/v1/projects/{pid}/bom/upload?label=GBK%20CSV",
        files={"file": ("bom_gbk.csv", content, "text/csv")},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["row_count"] == 3, f"GBK CSV 应解析出 3 行，实际 {body['row_count']}"

    # 描述不能是乱码
    items = client.get(f"/api/v1/bom/versions/{body['bom_version_id']}/items", headers=auth).json()
    descs = [i["description"] for i in items["items"]]
    assert any("厚膜贴片电阻" in d for d in descs), descs
    assert not any("\ufffd" in d for d in descs), "出现替换字符说明解码失败"

    # 用了非 UTF-8 编码要告诉用户，不然以后出现乱码没线索
    assert any(i.get("code") == "csv_encoding" for i in body["issues"]), body["issues"]


def test_upload_csv_utf8_bom(client, auth):
    """Excel 的「CSV UTF-8」会带 BOM，不能把 \ufeff 读进第一个表头。"""
    csv_text = "料号,规格描述,用量\nGRM188R71H104KA93D,陶瓷电容 0.1uF 50V 0603,20\n"
    p = client.post("/api/v1/projects", json={"name": "编码测试 UTF8"}, headers=auth)
    pid = p.json()["id"]

    r = client.post(
        f"/api/v1/projects/{pid}/bom/upload",
        files={"file": ("bom.csv", csv_text.encode("utf-8-sig"), "text/csv")},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["row_count"] == 1
    assert not any(i.get("code") == "csv_encoding" for i in r.json()["issues"])


def test_compare_two_assessments_route_not_shadowed(client, auth):
    """两个固定段路径（/assessments/compare 与 /assessments/{id}）的注册顺序。

    FastAPI 按注册顺序匹配。若 /assessments/{assessment_id} 先注册，
    /assessments/compare 会被当成 id="compare"，返回 422 int_parsing ——
    报告页的「两次评估对比」整块功能就是死的，而接口文档里看着一切正常。
    """
    aid = getattr(test_queue_and_confirm_then_assess, "assessment_id", None)
    assert aid

    # 同一个评估跟自己比：delta 必须全 0，这是最容易验证的稳定值
    r = client.get(f"/api/v1/assessments/compare?ids={aid},{aid}", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"left", "right", "delta"}
    assert body["delta"]["mtbf_change_pct"] == 0
    assert body["delta"]["r_change_pp"] == 0

    # 非法参数仍然要给人话，而不是 422 的 pydantic 原文
    bad = client.get("/api/v1/assessments/compare?ids=abc", headers=auth)
    assert bad.status_code == 400
    assert "ids" in bad.json()["detail"]


def test_report_xlsx_assumption_sheet_columns(client, auth):
    """XLSX「假设参数」的三个列必须各就各位。

    踩过的坑：拼行时对每行做了 r[1:]，把参数名砍掉，于是「参数」列装的是取值、
    「取值」列装的是说明。表格看着不报错，只是没人看得懂哪一行对应哪项假设。
    """
    import io

    from openpyxl import load_workbook

    aid = getattr(test_queue_and_confirm_then_assess, "assessment_id", None)
    assert aid
    r = client.post(f"/api/v1/assessments/{aid}/report", json={"kind": "xlsx"}, headers=auth)
    assert r.status_code == 200, r.text
    blob = client.get(f"/api/v1/reports/{r.json()['id']}/download", headers=auth).content

    ws = load_workbook(io.BytesIO(blob), data_only=True)["假设参数"]
    assert [c.value for c in ws[1]] == ["参数", "取值", "说明"], "表头被改动了"

    labels = [ws.cell(row=i, column=1).value for i in range(2, ws.max_row + 1)]
    assert "工作环境类别" in labels, f"参数名列丢了，实际第一列是 {labels[:3]}"
    assert "环境温度" in labels

    # 取值列不能是空的——空了就说明整行往左错了一格
    values = [ws.cell(row=i, column=2).value for i in range(2, ws.max_row + 1)]
    assert all(v not in (None, "") for v in values), f"取值列有空值：{values}"

    # 日通电时长要真的算出小时数。结果里只存 duty_cycle，直接读 duty_hours_per_day
    # 会得到 None，报告里就显示「— h/日」，而同一行 duty=0.333 明明是对的。
    duty = [v for (l, v) in zip(labels, values) if l == "日通电时长"][0]
    assert "—" not in duty, f"日通电时长没反算出来：{duty}"
    assert 0 < float(duty.split(" ")[0]) <= 24, f"日通电时长越界：{duty}"


def test_report_can_be_deleted(client, auth):
    """报告要能删。

    生成是幂等的反面——同一份评估点几次就多几份文件，历史默认全部保留。
    保留没问题，但得有出口：否则 data/reports 只涨不落，界面上也无从下手。
    """
    aid = getattr(test_queue_and_confirm_then_assess, "assessment_id", None)
    assert aid

    made = client.post(f"/api/v1/assessments/{aid}/report", json={"kind": "xlsx"}, headers=auth)
    assert made.status_code == 200, made.text
    rid = made.json()["id"]
    assert client.get(f"/api/v1/reports/{rid}/download", headers=auth).status_code == 200

    assert client.delete(f"/api/v1/reports/{rid}", headers=auth).status_code == 204

    # 记录与文件都要没了：再下载必须是 404，列表里也不该留死条目
    assert client.get(f"/api/v1/reports/{rid}/download", headers=auth).status_code == 404
    assert all(r["id"] != rid for r in client.get("/api/v1/reports", headers=auth).json())
    # 重复删除要给人话
    again = client.delete(f"/api/v1/reports/{rid}", headers=auth)
    assert again.status_code == 404
    assert "报告不存在" in again.json()["detail"]
