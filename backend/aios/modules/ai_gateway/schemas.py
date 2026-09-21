"""AI 结构化输出的 Schema 定义（规范 §21：模型输出必须以 Pydantic/JSON Schema 校验）。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ExtractedPosting(BaseModel):
    """抽取出的单条岗位（对应 prompts/job_extraction.v1.md 的输出契约）。"""

    title: str
    company_name: str = ""
    location: str = ""
    salary_text: str = ""
    description: str = ""
    url: str = ""
    external_id: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("title")
    @classmethod
    def _title_required(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("title 不能为空（没有岗位名的条目不应输出）")
        return value

    @field_validator("company_name", "location", "salary_text", "description", "url")
    @classmethod
    def _strip(cls, value: str) -> str:
        return (value or "").strip()


class PostingList(BaseModel):
    postings: list[ExtractedPosting] = Field(default_factory=list)


class JobSummary(BaseModel):
    """摘要类输出（规范 §21.2：job_summary 优先低成本文本模型）。"""

    summary: str = ""
    highlights: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
