"""跨模块契约（规范 §6.2-4：跨模块依赖必须经 contracts）：DTO、事件与来源策略。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from aios.core.ids import new_event_id

EventType = Literal[
    "job_posting.upserted.v1",
    "job_posting.blocked.v1",
    "crawl_run.finished.v1",
    "job_match.calculated.v1",
    "job_alert.triggered.v1",
]


class EventEnvelope(BaseModel):
    """标准事件信封（规范 §13）。"""

    event_id: str = Field(default_factory=new_event_id)
    event_type: EventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: str = ""
    aggregate: dict[str, str] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class JobSourcePolicy(BaseModel):
    """来源准入策略（规范 §14.1）：未配置或被禁用不得发起网络请求。"""

    domain: str
    access_method: Literal["manual_import", "public_html", "official_career", "rss", "api"] = "public_html"
    allowed_paths: list[str] = Field(default_factory=list)      # 空 = 仅域名根路径前缀
    rate_limit_per_minute: int = 6
    rate_limit_per_hour: int = 120
    daily_budget: int = 600
    max_page_depth: int = 3
    max_consecutive_failures: int = 3
    robots_checked_at: datetime | None = None
    terms_checked_at: datetime | None = None
    allow_auto_crawl: bool = False
    allow_fulltext: bool = False
    retention_days: int = 14
    note: str = ""


class ParsedJobPosting(BaseModel):
    """采集解析器的唯一输出（规范 §14.2 / §16.2）：不得直接写库。"""

    source_key: str                      # 来源标识（job_sources.name）
    external_id: str = ""
    canonical_url: str = ""
    company_name: str = ""
    title: str = ""
    location: str = ""
    work_mode: str = ""
    employment_type: str = ""
    seniority: str = ""
    description: str = ""
    salary_text: str = ""
    published_at: datetime | None = None
    raw_ref: str = ""
    confidence: float = 0.0
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "company_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return (v or "").strip()


class DiscoveredItem(BaseModel):
    """discover() 的输出：一个待抓取的条目。"""

    url: str
    hint_title: str = ""
    depth: int = 0
    external_id: str = ""


class DiscoveryPage(BaseModel):
    items: list[DiscoveredItem] = Field(default_factory=list)
    cursor: str | None = None
    exhausted: bool = True


class FetchedPage(BaseModel):
    url: str
    status: int = 200
    content: str = ""
    content_type: str = "text/html"
    blocked_reason: str = ""             # 403/429/验证码特征 → 立即停止该来源（规范 §14.1-4）


class SpiderHealth(BaseModel):
    source_key: str
    ok: bool
    detail: str = ""


class JobPostingOut(BaseModel):
    id: str
    source_id: str | None = None
    company_name: str = ""
    title: str = ""
    location: str = ""
    work_mode: str = ""
    employment_type: str = ""
    seniority: str = ""
    canonical_url: str = ""
    salary_text: str = ""
    status: str = "active"
    fingerprint: str = ""
    description: str = ""
    published_at: datetime | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    version: int = 1


class JobMatchOut(BaseModel):
    id: str
    job_posting_id: str
    score: float
    parts: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    profile_version: str = ""
    rule_version: str = ""
    model_version: str = ""
    calculated_at: datetime | None = None


class RadarCandidate(BaseModel):
    """既有岗位雷达的确定性候选行 → JIC 导入用的桥接 DTO（规范 §2.1-5「可插拔接入现有项目」）。"""

    title: str
    company_name: str = ""
    location: str = ""
    salary_text: str = ""
    platform: str = ""
    url: str = ""
    description: str = ""
    evidence: str = ""
