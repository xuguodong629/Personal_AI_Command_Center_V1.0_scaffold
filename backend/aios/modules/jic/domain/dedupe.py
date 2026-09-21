"""去重（规范 §16.1-Deduplicate）：先来源外部 ID，再 canonical URL，再指纹。

合并必须有规则（本函数返回命中原因，调用方写入审计与版本变更）。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from aios.contracts import ParsedJobPosting
from aios.modules.jic.models import JobPosting


@dataclass
class DedupHit:
    existing: JobPosting | None
    reason: str          # external_id | canonical_url | fingerprint | none


def find_duplicate(session: Session, *, parsed: ParsedJobPosting,
                   canonical_url: str, fingerprint_value: str) -> DedupHit:
    """按优先级查找已存在的职位记录。"""
    source_id = parsed.extra.get("source_id") if parsed.extra else None

    if parsed.external_id:
        q = session.query(JobPosting).filter(JobPosting.external_id == parsed.external_id)
        if source_id:
            q = q.filter(JobPosting.source_id == source_id)
        hit = q.first()
        if hit is not None:
            return DedupHit(hit, "external_id")

    if canonical_url:
        hit = session.query(JobPosting).filter(JobPosting.canonical_url == canonical_url).first()
        if hit is not None:
            return DedupHit(hit, "canonical_url")

    if fingerprint_value:
        hit = session.query(JobPosting).filter(JobPosting.fingerprint == fingerprint_value).first()
        if hit is not None:
            return DedupHit(hit, "fingerprint")

    return DedupHit(None, "none")


def changed_fields(old: JobPosting, parsed: ParsedJobPosting, canonical_url: str) -> list[str]:
    """计算发生变化的字段（用于 job_posting_versions.changed_fields）。"""
    pairs = {
        "title": (old.title, parsed.title),
        "company_name": (old.company_name, parsed.company_name),
        "location": (old.location, parsed.location),
        "description": (old.description, parsed.description),
        "salary_text": (old.salary_text, parsed.salary_text),
        "canonical_url": (old.canonical_url, canonical_url),
        "employment_type": (old.employment_type, parsed.employment_type),
        "seniority": (old.seniority, parsed.seniority),
    }
    return [name for name, (before, after) in pairs.items() if (before or "") != (after or "")]
