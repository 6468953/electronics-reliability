"""
app/schemas.py — 接口的输入/输出模型（Pydantic）

【这个模块做什么】
定义 Web 层的请求体与响应体。作用有三：
  1. 自动校验：前端传错类型、少字段，直接在入口拒绝，不污染数据库；
  2. 自动文档：FastAPI 用它生成 /docs 的交互式接口文档；
  3. 单一事实来源：前端 TS 类型由 OpenAPI 生成，前后端不会各写一套。

【命名约定】
  XxxCreate / XxxUpdate  = 请求体
  XxxOut                 = 响应体
计算结果的响应结构比较复杂（嵌套数组 + 可选字段），直接用 dict 返回，
因为它的形状由 core 的 dataclass 决定，硬拗成 Pydantic 模型会形成两套定义。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 认证 / 用户
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = ""
    role: str = Field(default="engineer", pattern="^(engineer|admin)$")


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool


# ---------------------------------------------------------------------------
# 项目
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(default="", max_length=64)
    description: str = ""
    target_years: float = 5.0
    target_survival: float = 0.95
    mtbf_threshold_hours: Optional[float] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    target_years: Optional[float] = None
    target_survival: Optional[float] = None
    mtbf_threshold_hours: Optional[float] = None
    status: Optional[str] = None


# ---------------------------------------------------------------------------
# BOM
# ---------------------------------------------------------------------------


class BomSimulateRequest(BaseModel):
    scale: int = Field(default=200, ge=10, le=5000, description="目标行数")
    seed: int = Field(default=42, description="随机种子，固定即复现")
    label: str = "模拟 BOM"
    include_cases: bool = Field(default=True, description="注入边界 case")
    include_dirty: bool = Field(default=True, description="注入脏数据（重复料号/缺数量）")


class BomItemUpdate(BaseModel):
    qty: Optional[int] = None
    ref_des: Optional[str] = None
    description: Optional[str] = None
    category_code: Optional[str] = None
    stress: Optional[Dict[str, float]] = None
    rated: Optional[Dict[str, float]] = None
    redundancy_group: Optional[str] = None
    redundancy_note: Optional[str] = None


# ---------------------------------------------------------------------------
# 分类
# ---------------------------------------------------------------------------


class ClassifyConfirm(BaseModel):
    category_code: str
    apply_to_similar: bool = Field(default=False, description="同时应用到描述高度相似的其他行")
    learn: bool = Field(default=True, description="把改判结果沉淀为知识库关键词")


class ClassifyBatchConfirm(BaseModel):
    item_ids: List[int]
    category_code: str
    learn: bool = True


class CategoryCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    parent_code: str = ""
    description: str = ""
    aliases: List[str] = []
    samples: List[str] = []


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    aliases: Optional[List[str]] = None
    samples: Optional[List[str]] = None
    is_active: Optional[bool] = None


class KeywordCreate(BaseModel):
    keyword: str = Field(min_length=1, max_length=64)
    weight: float = Field(default=2.0, ge=0.1, le=10)
    is_negative: bool = False


class KeywordUpdate(BaseModel):
    weight: Optional[float] = Field(default=None, ge=0.1, le=10)
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# 评估
# ---------------------------------------------------------------------------


class AssumptionIn(BaseModel):
    environment: str = "GB"
    ambient_temp_c: float = Field(default=40.0, ge=-60, le=150)
    quality_level: str = "commercial"
    duty_hours_per_day: float = Field(default=8.0, ge=0.1, le=24.0, description="日通电小时数")
    target_years: float = Field(default=5.0, gt=0, le=50)
    target_survival: float = Field(default=0.95, gt=0, lt=1)
    mtbf_threshold_hours: Optional[float] = None
    standard: str = Field(default="MIL-217F", pattern="^(MIL-217F|TELCORDIA_SR332)$")
    mode: str = Field(default="parts_count", pattern="^(parts_count|parts_stress)$")


class AssessRequest(BaseModel):
    assumption: AssumptionIn = AssumptionIn()
    bom_version_id: Optional[int] = None
    with_sensitivity: bool = True
    note: str = ""


class SensitivityRequest(BaseModel):
    variable: str = Field(default="ambient_temp", pattern="^(ambient_temp|quality_level|duty_cycle|environment)$")
    values: Optional[List[Union[float, str]]] = None


class ReportRequest(BaseModel):
    kind: str = Field(default="pdf", pattern="^(pdf|xlsx)$")
    title_note: str = ""


class BomItemPatchRows(BaseModel):
    """批量补录（降额缺数据、应力缺失时用）。"""

    item_id: int
    rated: Optional[Dict[str, float]] = None
    stress: Optional[Dict[str, float]] = None
