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
