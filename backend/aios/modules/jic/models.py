"""JIC 数据模型（规范 §15）：来源/采集/职位/版本/技能/匹配/用户状态/提醒。

规则要点：
- `(source_id, external_id)` 唯一；`canonical_url` 去参数后保存；`fingerprint` 用于近似去重。
- 职位数据与用户投递/收藏状态分离（`job_user_states`），避免来源信息被个人工作流字段污染。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aios.core.db import Base
from aios.core.mixins import SoftDeleteMixin, TimestampMixin


class Company(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "companies"
    __table_args__ = (Index("ix_companies_normalized_name", "normalized_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    website: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    industry: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    size_range: Mapped[str] = mapped_column(String(48), default="", nullable=False)


class JobSource(Base, TimestampMixin, SoftDeleteMixin):
    """来源注册表（规范 §14.1/§15）：未配置或被禁用 → 不得发起网络请求。"""

    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("name", name="uq_job_sources_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    source_type: Mapped[str] = mapped_column(String(48), default="public_html", nullable=False)
    policy: Mapped[str] = mapped_column(Text, default="{}", nullable=False)   # JobSourcePolicy JSON
    status: Mapped[str] = mapped_column(String(24), default="disabled", nullable=False, index=True)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_reason: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CrawlRun(Base, TimestampMixin):
    __tablename__ = "crawl_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("job_sources.id"), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(24), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="running", nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    error_code: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)


class CrawlItem(Base, TimestampMixin):
    """原始获取项目，按来源策略过期（规范 §15）。"""

    __tablename__ = "crawl_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    crawl_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("crawl_runs.id"), nullable=False, index=True)
    canonical_url: Mapped[str] = mapped_column(String(512), default="", nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    raw_ref: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobPosting(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_job_postings_source_id_external_id"),
        Index("ix_job_postings_fingerprint", "fingerprint"),
        Index("ix_job_postings_status_published_at", "status", "published_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("job_sources.id"), nullable=True)
    external_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(512), default="", nullable=False, index=True)
    company_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    company_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(120), default="", nullable=False, index=True)
    work_mode: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    employment_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    seniority: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    salary_text: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobPostingVersion(Base, TimestampMixin):
    __tablename__ = "job_posting_versions"
    __table_args__ = (UniqueConstraint("job_posting_id", "version", name="uq_job_posting_versions_job_posting_id_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_posting_id: Mapped[str] = mapped_column(String(36), ForeignKey("job_postings.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    changed_fields: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Skill(Base, TimestampMixin):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("normalized_name", name="uq_skills_normalized_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    normalized_name: Mapped[str] = mapped_column(String(96), nullable=False)
    category: Mapped[str] = mapped_column(String(48), default="", nullable=False)


class JobPostingSkill(Base, TimestampMixin):
    __tablename__ = "job_posting_skills"
    __table_args__ = (UniqueConstraint("job_posting_id", "skill_id", name="uq_job_posting_skills_posting_skill"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_posting_id: Mapped[str] = mapped_column(String(36), ForeignKey("job_postings.id"), nullable=False, index=True)
    skill_id: Mapped[str] = mapped_column(String(36), ForeignKey("skills.id"), nullable=False, index=True)
    importance: Mapped[str] = mapped_column(String(16), default="normal", nullable=False)
    evidence: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class JobMatch(Base, TimestampMixin):
    """匹配结果可解释、可重算（规范 §18）：保存分项、理由、缺口与各版本号。"""

    __tablename__ = "job_matches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_posting_id: Mapped[str] = mapped_column(String(36), ForeignKey("job_postings.id"), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(64), default="default", nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    parts: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    reasons: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    gaps: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    profile_version: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    rule_version: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    model_version: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobUserState(Base, TimestampMixin):
    """用户个人状态：saved / applied / archived（与职位来源数据分离）。"""

    __tablename__ = "job_user_states"
    __table_args__ = (UniqueConstraint("user_id", "job_posting_id", name="uq_job_user_states_user_posting"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    job_posting_id: Mapped[str] = mapped_column(String(36), ForeignKey("job_postings.id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(24), default="saved", nullable=False, index=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobAlert(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "job_alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    query_spec: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    threshold: Mapped[float] = mapped_column(Float, default=70.0, nullable=False)
    delivery_channel: Mapped[str] = mapped_column(String(32), default="inbox", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
