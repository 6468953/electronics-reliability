"""
app/models.py — 数据库模型（ORM）

【这个模块做什么】
定义系统的全部数据表。按"一条主线"排列：

    用户 → 项目 → BOM 版本 → BOM 行 → （分类结果/应力/额定值）
                              ↓
                          评估记录 → 逐零件结果 / 磨损 / 降额 / 敏感性
                              ↓
                            报告文件

外加两条支线：
    分类知识库（类目 + 关键词 + 确认反馈）——支撑"越用越准"
    操作日志——审计

【设计上两个关键选择】
1. 【评估结果存快照，不存外键关联的实时值】
   参数库会升级、知识库会被改，如果报告每次重新按当前参数算，历史结论就会"变"。
   所以 assessments 里存 assumptions_json / param_version / engine_version，
   结果也整份存下来（result_json）。报告复现的前提是快照。

2. 【bom_items 同时存"解析值"和"人工值"】
   rated_json 可能是从描述解析的，也可能是人工补录的；rated_source 记录来源。
   没有这个字段，出了问题无法回答"这个数是谁给的"。同理 stress_json。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now()


# ---------------------------------------------------------------------------
# 账户与项目
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(16), default="engineer")  # engineer | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    projects: Mapped[list["Project"]] = relationship(back_populates="owner")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    description: Mapped[str] = mapped_column(Text, default="")

    target_years: Mapped[float] = mapped_column(Float, default=5.0)
    target_survival: Mapped[float] = mapped_column(Float, default=0.95)
    mtbf_threshold_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # draft → bom_ready → classified → assessed → reported → archived
    status: Mapped[str] = mapped_column(String(24), default="draft")
    current_bom_version_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    owner: Mapped[User] = relationship(back_populates="projects")
    bom_versions: Mapped[list["BomVersion"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    assessments: Mapped[list["Assessment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# BOM
# ---------------------------------------------------------------------------


class BomVersion(Base):
    __tablename__ = "bom_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(String(64), default="基准方案")
    source: Mapped[str] = mapped_column(String(16), default="upload")  # upload | simulated
    filename: Mapped[str] = mapped_column(String(255), default="")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    qty_total: Mapped[int] = mapped_column(Integer, default=0)
    parse_warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    uploaded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="bom_versions")
    items: Mapped[list["BomItem"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    issues: Mapped[list["BomParseIssue"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class BomItem(Base):
    __tablename__ = "bom_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_version_id: Mapped[int] = mapped_column(ForeignKey("bom_versions.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer, default=0)
    part_number: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    qty: Mapped[int] = mapped_column(Integer, default=1)
    ref_des: Mapped[str] = mapped_column(String(255), default="")

    # 分类结果
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    category_source: Mapped[str] = mapped_column(String(16), default="")   # auto/manual/learned
    match_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    match_status: Mapped[str] = mapped_column(String(20), default="unclassified")
    candidate_json: Mapped[str] = mapped_column(Text, default="[]")
    match_reason: Mapped[str] = mapped_column(Text, default="")
    confirmed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 工程数据
    rated_json: Mapped[str] = mapped_column(Text, default="{}")
    rated_source: Mapped[str] = mapped_column(String(16), default="")
    stress_json: Mapped[str] = mapped_column(Text, default="{}")
    redundancy_group: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    redundancy_note: Mapped[str] = mapped_column(String(255), default="")

    version: Mapped[BomVersion] = relationship(back_populates="items")
    category: Mapped[Optional["Category"]] = relationship()


class BomParseIssue(Base):
    __tablename__ = "bom_parse_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_version_id: Mapped[int] = mapped_column(ForeignKey("bom_versions.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(8), default="warn")   # error | warn
    code: Mapped[str] = mapped_column(String(32), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    line_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    version: Mapped[BomVersion] = relationship(back_populates="issues")


# ---------------------------------------------------------------------------
# 分类知识库
# ---------------------------------------------------------------------------


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    parent_code: Mapped[str] = mapped_column(String(32), default="")   # 大类编码
    name: Mapped[str] = mapped_column(String(64))
    level: Mapped[int] = mapped_column(Integer, default=2)             # 1=大类 2=小类
    description: Mapped[str] = mapped_column(Text, default="")
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    samples_json: Mapped[str] = mapped_column(Text, default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    keywords: Mapped[list["CategoryKeyword"]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )


class CategoryKeyword(Base):
    __tablename__ = "category_keywords"
    __table_args__ = (UniqueConstraint("category_id", "keyword", "is_negative", name="uq_kw"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    keyword: Mapped[str] = mapped_column(String(64))
    weight: Mapped[float] = mapped_column(Float, default=2.0)
    is_negative: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(16), default="seed")    # seed | learned | manual
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    category: Mapped[Category] = relationship(back_populates="keywords")


class ClassifyFeedback(Base):
    """人工确认/改判的原始记录。用于统计"引擎准确率"和回溯学习效果。"""

    __tablename__ = "classify_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    suggested_code: Mapped[str] = mapped_column(String(32), default="")
    final_code: Mapped[str] = mapped_column(String(32), default="")
    match_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)   # 是否接受了机器建议
    learned_keywords: Mapped[str] = mapped_column(Text, default="[]")
    operator_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------------------------------------------------------------------------
# 评估
# ---------------------------------------------------------------------------


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    bom_version_id: Mapped[int] = mapped_column(ForeignKey("bom_versions.id"), index=True)
    standard: Mapped[str] = mapped_column(String(32), default="MIL-217F")
    mode: Mapped[str] = mapped_column(String(20), default="parts_count")
    assumptions_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    param_version: Mapped[str] = mapped_column(String(32), default="")
    engine_version: Mapped[str] = mapped_column(String(32), default="1.0.0")

    lambda_total_fit: Mapped[float] = mapped_column(Float, default=0.0)
    mtbf_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    r_at_target: Mapped[float] = mapped_column(Float, default=0.0)
    verdict: Mapped[str] = mapped_column(String(8), default="NA")
    compare_group_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="assessments")
    items: Mapped[list["AssessmentItem"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class AssessmentItem(Base):
    """逐零件的计算明细。trace_json 是"计算过程可追溯"的落库位置。"""

    __tablename__ = "assessment_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    bom_item_id: Mapped[int] = mapped_column(Integer, default=0)
    part_number: Mapped[str] = mapped_column(String(128), default="")
    category_code: Mapped[str] = mapped_column(String(32), default="")
    category_name: Mapped[str] = mapped_column(String(64), default="")
    qty: Mapped[int] = mapped_column(Integer, default=1)
    lambda_b: Mapped[float] = mapped_column(Float, default=0.0)
    factors_json: Mapped[str] = mapped_column(Text, default="{}")
    lambda_part: Mapped[float] = mapped_column(Float, default=0.0)
    contribution_pct: Mapped[float] = mapped_column(Float, default=0.0)
    trace_json: Mapped[str] = mapped_column(Text, default="[]")

    assessment: Mapped[Assessment] = relationship(back_populates="items")


class WearResultRow(Base):
    __tablename__ = "wear_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    bom_item_id: Mapped[int] = mapped_column(Integer, default=0)
    part_number: Mapped[str] = mapped_column(String(128), default="")
    mechanism: Mapped[str] = mapped_column(String(48), default="")
    mechanism_label: Mapped[str] = mapped_column(String(64), default="")
    life_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    life_years: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    formula: Mapped[str] = mapped_column(Text, default="")
    inputs_json: Mapped[str] = mapped_column(Text, default="{}")
    using_defaults_json: Mapped[str] = mapped_column(Text, default="[]")
    is_limiting: Mapped[bool] = mapped_column(Boolean, default=False)


class DeratingResultRow(Base):
    __tablename__ = "derating_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    bom_item_id: Mapped[int] = mapped_column(Integer, default=0)
    part_number: Mapped[str] = mapped_column(String(128), default="")
    category_code: Mapped[str] = mapped_column(String(32), default="")
    stress_type: Mapped[str] = mapped_column(String(16), default="")
    rated_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    applied_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    verdict: Mapped[str] = mapped_column(String(16), default="no_data")
    note: Mapped[str] = mapped_column(Text, default="")


class SensitivityRun(Base):
    __tablename__ = "sensitivity_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    variable: Mapped[str] = mapped_column(String(32), default="ambient_temp")
    sweep_json: Mapped[str] = mapped_column(Text, default="{}")
    elasticity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8), default="pdf")
    file_path: Mapped[str] = mapped_column(String(512), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    verdict: Mapped[str] = mapped_column(String(8), default="NA")
    generated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64), default="")
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
