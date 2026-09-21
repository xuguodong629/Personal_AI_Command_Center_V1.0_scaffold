"""JIC 仓储（规范 §6.1-Infrastructure）：SQL 只出现在这一层，应用服务依赖仓储接口。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from aios.contracts import JobSourcePolicy, ParsedJobPosting
from aios.core.ids import new_uuid
from aios.modules.jic.domain.normalize import fingerprint as make_fingerprint
from aios.modules.jic.models import (
    Company,
    CrawlItem,
    CrawlRun,
    JobAlert,
    JobMatch,
    JobPosting,
    JobPostingVersion,
    JobSource,
    JobUserState,
)


class JobSourceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, *, status: str = "", limit: int = 100) -> list[JobSource]:
        q = self.session.query(JobSource).filter(JobSource.deleted_at.is_(None))
        if status:
            q = q.filter(JobSource.status == status)
        return q.order_by(JobSource.created_at.desc()).limit(limit).all()

    def get(self, source_id: str) -> JobSource | None:
        return self.session.get(JobSource, source_id)

    def get_by_name(self, name: str) -> JobSource | None:
        return self.session.query(JobSource).filter(JobSource.name == name).one_or_none()

    def create(self, *, name: str, base_url: str, source_type: str, policy: JobSourcePolicy,
               status: str = "enabled", actor_id: str = "") -> JobSource:
        row = JobSource(id=new_uuid(), name=name, base_url=base_url, source_type=source_type,
                        policy=policy.model_dump_json(), status=status,
                        rate_limit_per_minute=policy.rate_limit_per_minute,
                        created_by=actor_id, updated_by=actor_id)
        self.session.add(row)
        self.session.flush()
        return row

    def update(self, row: JobSource, **fields) -> JobSource:
        for key, value in fields.items():
            if hasattr(row, key) and value is not None:
                setattr(row, key, value)
        self.session.flush()
        return row

    def record_failure(self, row: JobSource, reason: str, max_failures: int) -> JobSource:
        row.consecutive_failures += 1
        if row.consecutive_failures >= max_failures:
            row.status = "blocked"
            row.blocked_reason = reason[:160]
        self.session.flush()
        return row

    def record_success(self, row: JobSource) -> JobSource:
        row.consecutive_failures = 0
        row.blocked_reason = ""
        row.last_run_at = datetime.now(timezone.utc)
        self.session.flush()
        return row


class CrawlRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start_run(self, *, source_id: str, trigger: str = "manual") -> CrawlRun:
        row = CrawlRun(id=new_uuid(), source_id=source_id, trigger=trigger, status="running",
                       started_at=datetime.now(timezone.utc), stats="{}")
        self.session.add(row)
        self.session.flush()
        return row

    def finish_run(self, row: CrawlRun, *, status: str, stats: str = "{}",
                   error_code: str = "", error_message: str = "") -> CrawlRun:
        row.status = status
        row.stats = stats
        row.error_code = error_code
        row.error_message = error_message[:2000]
        row.finished_at = datetime.now(timezone.utc)
        self.session.flush()
        return row

    def get_run(self, run_id: str) -> CrawlRun | None:
        return self.session.get(CrawlRun, run_id)

    def add_item(self, *, run_id: str, canonical_url: str, content_hash: str, http_status: int,
                 parse_status: str, raw_ref: str, retention_days: int) -> CrawlItem:
        from datetime import timedelta
        row = CrawlItem(id=new_uuid(), crawl_run_id=run_id, canonical_url=canonical_url[:512],
                        content_hash=content_hash, http_status=http_status, parse_status=parse_status,
                        raw_ref=raw_ref[:255],
                        expires_at=datetime.now(timezone.utc) + timedelta(days=max(1, retention_days)))
        self.session.add(row)
        self.session.flush()
        return row


class JobPostingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, *, parsed: ParsedJobPosting, source_id: str | None, existing: JobPosting | None,
               company_id: str | None, canonical_url: str, content_hash: str,
               changed: list[str], actor_id: str = "") -> tuple[JobPosting, int]:
        """新建或更新职位，并在变化时写入版本记录。返回 (职位, 版本号)。"""
        now = datetime.now(timezone.utc)
        fingerprint_value = make_fingerprint(company=parsed.company_name, title=parsed.title,
                                             location=parsed.location, domain=parsed.raw_ref,
                                             description=parsed.description)
        if existing is None:
            row = JobPosting(
                id=new_uuid(), source_id=source_id, external_id=parsed.external_id[:128],
                canonical_url=canonical_url[:512], company_id=company_id,
                company_name=parsed.company_name[:200], title=parsed.title[:255],
                location=parsed.location[:120], work_mode=parsed.work_mode[:32],
                employment_type=parsed.employment_type[:32], seniority=parsed.seniority[:32],
                description=parsed.description, salary_text=parsed.salary_text[:120],
                published_at=parsed.published_at, status="active", fingerprint=fingerprint_value,
                content_hash=content_hash, first_seen_at=now, last_seen_at=now,
                created_by=actor_id, updated_by=actor_id,
            )
            self.session.add(row)
            self.session.flush()
            version = self._add_version(row, changed=changed or ["<created>"], actor_id=actor_id)
            return row, version

        existing.last_seen_at = now
        if changed:
            existing.title = parsed.title[:255] or existing.title
            existing.company_name = parsed.company_name[:200] or existing.company_name
            existing.location = parsed.location[:120] or existing.location
            existing.description = parsed.description or existing.description
            existing.salary_text = parsed.salary_text[:120] or existing.salary_text
            existing.canonical_url = canonical_url[:512] or existing.canonical_url
            existing.employment_type = parsed.employment_type[:32] or existing.employment_type
            existing.seniority = parsed.seniority[:32] or existing.seniority
            existing.content_hash = content_hash
            existing.fingerprint = fingerprint_value
            existing.updated_by = actor_id
            self.session.flush()
            return existing, self._add_version(existing, changed=changed, actor_id=actor_id)
        self.session.flush()
        return existing, self._latest_version(existing.id)

    def _add_version(self, job: JobPosting, *, changed: list[str], actor_id: str) -> int:
        import json as _json
        version = self._latest_version(job.id) + 1
        self.session.add(JobPostingVersion(
            id=new_uuid(), job_posting_id=job.id, version=version, content_hash=job.content_hash,
            changed_fields=_json.dumps(changed, ensure_ascii=False),
            captured_at=datetime.now(timezone.utc), created_by=actor_id, updated_by=actor_id,
        ))
        self.session.flush()
        return version

    def _latest_version(self, job_id: str) -> int:
        value = self.session.query(func.max(JobPostingVersion.version)).filter(
            JobPostingVersion.job_posting_id == job_id).scalar()
        return int(value or 0)

    def get(self, job_id: str) -> JobPosting | None:
        return self.session.get(JobPosting, job_id)

    def list(self, *, q: str = "", company_id: str = "", location: str = "", work_mode: str = "",
             employment_type: str = "", seniority: str = "", status: str = "",
             source_id: str = "", page: int = 1, page_size: int = 20) -> tuple[list[JobPosting], int]:
        """列表过滤白名单（规范 §17）：全部参数化查询，不拼接 SQL。"""
        query = self.session.query(JobPosting).filter(JobPosting.deleted_at.is_(None))
        if q:
            like = f"%{q}%"
            query = query.filter(or_(JobPosting.title.ilike(like), JobPosting.company_name.ilike(like),
                                     JobPosting.description.ilike(like)))
        if company_id:
            query = query.filter(JobPosting.company_id == company_id)
        if location:
            query = query.filter(JobPosting.location.ilike(f"%{location}%"))
        if work_mode:
            query = query.filter(JobPosting.work_mode == work_mode)
        if employment_type:
            query = query.filter(JobPosting.employment_type == employment_type)
        if seniority:
            query = query.filter(JobPosting.seniority == seniority)
        if status:
            query = query.filter(JobPosting.status == status)
        if source_id:
            query = query.filter(JobPosting.source_id == source_id)
        total = query.count()
        rows = (query.order_by(JobPosting.first_seen_at.desc().nullslast(), JobPosting.id)
                .offset(max(0, (page - 1) * page_size)).limit(page_size).all())
        return rows, total

    def versions(self, job_id: str) -> list[JobPostingVersion]:
        return (self.session.query(JobPostingVersion)
                .filter(JobPostingVersion.job_posting_id == job_id)
                .order_by(JobPostingVersion.version.desc()).all())


class CompanyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(self, *, normalized_name: str, industry: str = "") -> Company | None:
        if not normalized_name:
            return None
        row = (self.session.query(Company)
               .filter(Company.normalized_name == normalized_name, Company.deleted_at.is_(None))
               .one_or_none())
        if row is not None:
            return row
        row = Company(id=new_uuid(), normalized_name=normalized_name[:200], industry=industry[:96])
        self.session.add(row)
        self.session.flush()
        return row


class MatchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def replace(self, *, job_posting_id: str, profile_id: str, score: float, parts: dict,
                reasons: list[str], gaps: list[str], profile_version: str, rule_version: str,
                model_version: str, input_hash: str) -> JobMatch:
        import json as _json
        row = (self.session.query(JobMatch)
               .filter(JobMatch.job_posting_id == job_posting_id, JobMatch.profile_id == profile_id)
               .one_or_none())
        if row is None:
            row = JobMatch(id=new_uuid(), job_posting_id=job_posting_id, profile_id=profile_id)
            self.session.add(row)
        row.score = score
        row.parts = _json.dumps(parts, ensure_ascii=False)
        row.reasons = _json.dumps(reasons, ensure_ascii=False)
        row.gaps = _json.dumps(gaps, ensure_ascii=False)
        row.profile_version = profile_version
        row.rule_version = rule_version
        row.model_version = model_version
        row.input_hash = input_hash
        row.calculated_at = datetime.now(timezone.utc)
        self.session.flush()
        return row

    def get(self, *, job_posting_id: str, profile_id: str = "default") -> JobMatch | None:
        return (self.session.query(JobMatch)
                .filter(JobMatch.job_posting_id == job_posting_id, JobMatch.profile_id == profile_id)
                .one_or_none())


class UserStateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def set_state(self, *, user_id: str, job_posting_id: str, state: str, notes: str = "") -> JobUserState:
        row = (self.session.query(JobUserState)
               .filter(JobUserState.user_id == user_id, JobUserState.job_posting_id == job_posting_id)
               .one_or_none())
        now = datetime.now(timezone.utc)
        if row is None:
            row = JobUserState(id=new_uuid(), user_id=user_id, job_posting_id=job_posting_id)
            self.session.add(row)
        row.state = state
        if notes:
            row.notes = notes
        if state == "saved" and row.saved_at is None:
            row.saved_at = now
        if state == "applied" and row.applied_at is None:
            row.applied_at = now
        self.session.flush()
        return row

    def get(self, *, user_id: str, job_posting_id: str) -> JobUserState | None:
        return (self.session.query(JobUserState)
                .filter(JobUserState.user_id == user_id, JobUserState.job_posting_id == job_posting_id)
                .one_or_none())


class AlertRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, user_id: str, query_spec: dict, threshold: float, delivery_channel: str) -> JobAlert:
        import json as _json
        row = JobAlert(id=new_uuid(), user_id=user_id, query_spec=_json.dumps(query_spec, ensure_ascii=False),
                       threshold=threshold, delivery_channel=delivery_channel, enabled=True)
        self.session.add(row)
        self.session.flush()
        return row

    def list(self, *, user_id: str = "") -> list[JobAlert]:
        q = self.session.query(JobAlert).filter(JobAlert.deleted_at.is_(None))
        if user_id:
            q = q.filter(JobAlert.user_id == user_id)
        return q.order_by(JobAlert.created_at.desc()).limit(100).all()

    def set_enabled(self, alert_id: str, enabled: bool) -> JobAlert | None:
        row = self.session.get(JobAlert, alert_id)
        if row is not None:
            row.enabled = enabled
            self.session.flush()
        return row
