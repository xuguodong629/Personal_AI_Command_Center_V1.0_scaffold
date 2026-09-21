"""JIC 应用服务（规范 §16）：准入 → 抓取 → 解析 → 规范化 → 校验 → 去重 → 持久化 → 事件 → 匹配。

用例编排、事务边界与授权检查都在这一层（规范 §6.1）；领域规则在 domain/，SQL 在 infrastructure/。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from aios.contracts import DiscoveredItem, EventEnvelope, JobSourcePolicy, ParsedJobPosting, RadarCandidate
from aios.core.errors import AIOSError, ErrorCode, NotFoundError, SourceNotAllowedError
from aios.core.http import Actor
from aios.core.logging import get_logger, log_extra
from aios.core.outbox import enqueue, new_aggregate
from aios.modules.audit import service as audit
from aios.modules.jic.domain import matching
from aios.modules.jic.domain.dedupe import changed_fields, find_duplicate
from aios.modules.jic.domain.normalize import (
    canonicalize_url,
    detect_employment_type,
    detect_seniority,
    detect_work_mode,
    fingerprint,
    host_of,
    normalize_company,
    parse_salary_text,
    sha256_text,
)
from aios.modules.jic.infrastructure.repositories import (
    AlertRepository,
    CompanyRepository,
    CrawlRepository,
    JobPostingRepository,
    JobSourceRepository,
    MatchRepository,
    UserStateRepository,
)
from aios.modules.jic.infrastructure.spiders import spider_manager

logger = get_logger("aios.jic")

MIN_CONFIDENCE = 0.5          # 低于此值转人工复核（规范 §16.1-Validate）
MAX_ITEMS_PER_RUN = 40        # 禁止无上限翻页（规范 §16.1-Fetch）


@dataclass
class ImportStats:
    received: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    needs_review: int = 0
    rejected: int = 0
    dedup_reasons: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"received": self.received, "created": self.created, "updated": self.updated,
                "unchanged": self.unchanged, "needs_review": self.needs_review,
                "rejected": self.rejected, "dedup_reasons": self.dedup_reasons}


class JICService:
    """JIC 应用服务。所有写操作在同一事务内完成并写审计与 Outbox（规范 §13）。"""

    def __init__(self, session: Session, actor: Actor | None = None) -> None:
        self.session = session
        self.actor = actor or Actor(actor_id="system", workspace_id="system")
        self.sources = JobSourceRepository(session)
        self.crawls = CrawlRepository(session)
        self.jobs = JobPostingRepository(session)
        self.companies = CompanyRepository(session)
        self.matches = MatchRepository(session)
        self.states = UserStateRepository(session)
        self.alerts = AlertRepository(session)

    # ---------------------------------------------------------- 来源（§14.1）
    def create_source(self, *, name: str, base_url: str, source_type: str,
                      policy: JobSourcePolicy, status: str = "enabled") -> dict[str, Any]:
        if source_type not in spider_manager.registered_types():
            raise AIOSError(ErrorCode.VALIDATION_ERROR, f"未注册的来源类型：{source_type}",
                            [{"field": "source_type", "reason": "unknown",
                              "registered": spider_manager.registered_types()}])
        existing = self.sources.get_by_name(name)
        if existing is not None:
            raise AIOSError(ErrorCode.CONFLICT, f"来源已存在：{name}")
        row = self.sources.create(name=name, base_url=base_url, source_type=source_type,
                                  policy=policy, status=status, actor_id=self.actor.actor_id)
        audit.record(self.session, action="source.create", actor=self.actor, resource_type="job_source",
                     resource_id=row.id, after_summary=f"{name} {base_url} type={source_type} status={status}")
        return _source_out(row)

    def update_source(self, source_id: str, *, status: str = "", policy: JobSourcePolicy | None = None) -> dict[str, Any]:
        row = self.sources.get(source_id)
        if row is None:
            raise NotFoundError("来源", source_id)
        before = f"status={row.status}"
        fields: dict[str, Any] = {}
        if status:
            fields["status"] = status
            fields["blocked_reason"] = "" if status == "enabled" else row.blocked_reason
            fields["consecutive_failures"] = 0 if status == "enabled" else row.consecutive_failures
        if policy is not None:
            fields["policy"] = policy.model_dump_json()
            fields["rate_limit_per_minute"] = policy.rate_limit_per_minute
        self.sources.update(row, **fields)
        audit.record(self.session, action="source.update", actor=self.actor, resource_type="job_source",
                     resource_id=row.id, before_summary=before, after_summary=f"status={row.status}")
        return _source_out(row)

    def list_sources(self, *, status: str = "") -> list[dict[str, Any]]:
        return [_source_out(x) for x in self.sources.list(status=status)]

    def source_health(self) -> list[dict[str, Any]]:
        out = []
        for row in self.sources.list():
            policy = _policy_of(row)
            health = spider_manager.health(source_type=row.source_type, base_url=row.base_url,
                                                  policy=policy)
            out.append({**_source_out(row), "health": health.model_dump()})
        return out

    # ---------------------------------------------------------- 采集（§16）
    def run_source(self, source_id: str, *, trigger: str = "manual",
                   settings: dict[str, Any] | None = None) -> dict[str, Any]:
        """受控采集：Preflight → Fetch → Parse → Normalize → Validate → Dedupe → Persist。"""
        row = self.sources.get(source_id)
        if row is None:
            raise NotFoundError("来源", source_id)
        policy = _policy_of(row)
        self._preflight(row, policy)                       # 规范 §14.1-1/2/3
        run = self.crawls.start_run(source_id=source_id, trigger=trigger)
        audit.record(self.session, action="source.run", actor=self.actor, resource_type="job_source",
                     resource_id=source_id, after_summary=f"crawl_run={run.id} trigger={trigger}")
        stats = ImportStats()
        blocked_reason = ""
        parsed_rows: list[ParsedJobPosting] = []
        try:
            spider = spider_manager.create(source_type=row.source_type, base_url=row.base_url,
                                                  settings=settings or {}, policy=policy)
            discovery = spider.discover()
            items: list[DiscoveredItem] = discovery.items[:MAX_ITEMS_PER_RUN]
            interval = 60.0 / max(1, policy.rate_limit_per_minute)   # 按来源限速（规范 §19-来源预算）
            for index, item in enumerate(items):
                if index:
                    time.sleep(min(interval, 5.0))
                page = spider.fetch(item)
                parse_status = "parsed"
                if page.blocked_reason:
                    blocked_reason = page.blocked_reason
                    self.crawls.add_item(run_id=run.id, canonical_url=canonicalize_url(page.url),
                                         content_hash="", http_status=page.status,
                                         parse_status="blocked", raw_ref=host_of(page.url),
                                         retention_days=policy.retention_days)
                    break                                   # 立即停止该来源（规范 §14.1-4）
                if page.status >= 400:
                    self.crawls.add_item(run_id=run.id, canonical_url=canonicalize_url(page.url),
                                         content_hash=sha256_text(page.content), http_status=page.status,
                                         parse_status="http_error", raw_ref=host_of(page.url),
                                         retention_days=policy.retention_days)
                    continue
                parsed = spider.parse(page)
                if parsed.confidence < MIN_CONFIDENCE:
                    parse_status = "needs_review"
                    stats.needs_review += 1
                else:
                    parsed_rows.append(parsed)
                self.crawls.add_item(run_id=run.id, canonical_url=canonicalize_url(page.url),
                                     content_hash=sha256_text(page.content), http_status=page.status,
                                     parse_status=parse_status,
                                     raw_ref=host_of(page.url) if not policy.allow_fulltext else page.url,
                                     retention_days=policy.retention_days)
            for parsed in parsed_rows:
                self._persist(parsed, source_id=source_id, stats=stats)
        except AIOSError as exc:
            self.crawls.finish_run(run, status="failed", stats=json.dumps(stats.as_dict(), ensure_ascii=False),
                                   error_code=exc.code.value, error_message=exc.message)
            self.sources.record_failure(row, exc.code.value,
                                        policy.max_consecutive_failures or 3)
            raise
        finally:
            if blocked_reason:
                self.crawls.finish_run(run, status="blocked",
                                       stats=json.dumps(stats.as_dict(), ensure_ascii=False),
                                       error_code=ErrorCode.JOB_SOURCE_BLOCKED.value,
                                       error_message=f"来源返回封禁/风控特征：{blocked_reason}")
                self.sources.record_failure(row, f"blocked:{blocked_reason}",
                                            policy.max_consecutive_failures or 3)
                logger.warning("source_blocked", extra=log_extra(source_id=source_id,
                                                                 error_code=blocked_reason))
            elif run.status == "running":
                self.crawls.finish_run(run, status="succeeded",
                                       stats=json.dumps(stats.as_dict(), ensure_ascii=False))
                self.sources.record_success(row)
        return {"crawl_run_id": run.id, "status": run.status, "stats": stats.as_dict(),
                "blocked_reason": blocked_reason}

    def _preflight(self, row, policy: JobSourcePolicy) -> None:
        """准入检查（规范 §14.1）：未配置或被禁用不得发起网络请求。"""
        if row.status == "disabled":
            raise AIOSError(ErrorCode.JOB_SOURCE_DISABLED, "来源已禁用，不得发起请求")
        if row.status == "blocked":
            raise AIOSError(ErrorCode.JOB_SOURCE_BLOCKED, f"来源已被标记 blocked：{row.blocked_reason}")
        if not row.base_url:
            raise SourceNotAllowedError(reason="base_url_missing")
        if not policy.domain:
            raise SourceNotAllowedError(row.base_url, "policy_domain_missing")
        if row.source_type != "manual_import" and not policy.allow_auto_crawl:
            raise SourceNotAllowedError(row.base_url, "auto_crawl_not_allowed")
        if not policy.robots_checked_at:
            raise SourceNotAllowedError(row.base_url, "robots_not_checked")

    # ---------------------------------------------------------- 导入与持久化
    def import_candidates(self, candidates: list[RadarCandidate], *, source_id: str | None = None,
                          source_key: str = "radar", actor_note: str = "") -> dict[str, Any]:
        """把手动粘贴/岗位雷达的候选行导入 JIC（规范 §14「输入可以是用户手动粘贴」）。"""
        stats = ImportStats(received=len(candidates))
        for cand in candidates:
            parsed = _candidate_to_parsed(cand, source_key=source_key)
            self._persist(parsed, source_id=source_id, stats=stats)
        audit.record(self.session, action="job_posting.import", actor=self.actor,
                     resource_type="job_posting", resource_id=source_id or source_key,
                     after_summary=f"received={stats.received} created={stats.created} "
                                   f"updated={stats.updated} unchanged={stats.unchanged} {actor_note}")
        return stats.as_dict()

    def _persist(self, parsed: ParsedJobPosting, *, source_id: str | None, stats: ImportStats) -> None:
        """规范化 → 校验 → 去重 → 持久化 + 版本 + Outbox + 匹配。"""
        canonical = canonicalize_url(parsed.canonical_url)
        if not parsed.title or not (canonical or parsed.external_id):
            stats.rejected += 1
            return                                   # 标题、链接/来源外部 ID 为必填（规范 §16.1-Validate）
        parsed.location = parsed.location or ""
        parsed.company_name = parsed.company_name or ""
        content_hash = sha256_text("|".join([parsed.title, parsed.company_name, parsed.location,
                                             parsed.description, parsed.salary_text]))
        fingerprint_value = fingerprint(company=parsed.company_name, title=parsed.title,
                                        location=parsed.location, domain=parsed.raw_ref or host_of(canonical),
                                        description=parsed.description)
        hit = find_duplicate(self.session, parsed=parsed, canonical_url=canonical,
                             fingerprint_value=fingerprint_value)
        stats.dedup_reasons[hit.reason] = stats.dedup_reasons.get(hit.reason, 0) + 1
        company = self.companies.get_or_create(normalized_name=normalize_company(parsed.company_name))
        changed = changed_fields(hit.existing, parsed, canonical) if hit.existing else []
        job, version = self.jobs.upsert(parsed=parsed, source_id=source_id or parsed.extra.get("source_id"),
                                        existing=hit.existing, company_id=company.id if company else None,
                                        canonical_url=canonical, content_hash=content_hash,
                                        changed=changed, actor_id=self.actor.actor_id)
        if hit.existing is None:
            stats.created += 1
        elif changed:
            stats.updated += 1
        else:
            stats.unchanged += 1
        enqueue(self.session, EventEnvelope(
            event_type="job_posting.upserted.v1",
            aggregate=new_aggregate("job_posting", job.id),
            data={"job_posting_id": job.id, "version": version, "dedup_reason": hit.reason,
                  "changed_fields": changed, "title": job.title, "company": job.company_name},
        ))
        self.calculate_match(job)

    # ---------------------------------------------------------- 查询与状态
    def list_jobs(self, **filters) -> tuple[list[dict[str, Any]], int]:
        rows, total = self.jobs.list(**filters)
        return [_job_out(x, self.matches.get(job_posting_id=x.id)) for x in rows], total

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self.jobs.get(job_id)
        if row is None:
            raise NotFoundError("职位", job_id)
        payload = _job_out(row, self.matches.get(job_posting_id=row.id))
        payload["versions"] = [{"version": v.version, "content_hash": v.content_hash,
                                "changed_fields": json.loads(v.changed_fields or "[]"),
                                "captured_at": v.captured_at} for v in self.jobs.versions(job_id)]
        payload["user_state"] = None
        state = self.states.get(user_id=self.actor.actor_id, job_posting_id=job_id)
        if state is not None:
            payload["user_state"] = {"state": state.state, "notes": state.notes,
                                     "saved_at": state.saved_at, "applied_at": state.applied_at}
        return payload

    def set_state(self, job_id: str, *, state: str, notes: str = "") -> dict[str, Any]:
        if self.jobs.get(job_id) is None:
            raise NotFoundError("职位", job_id)
        if state not in ("saved", "applied", "archived", "none"):
            raise AIOSError(ErrorCode.VALIDATION_ERROR, f"不支持的状态：{state}",
                            [{"field": "state", "reason": "not_allowed"}])
        row = self.states.set_state(user_id=self.actor.actor_id, job_posting_id=job_id, state=state, notes=notes)
        audit.record(self.session, action="job_posting.state_change", actor=self.actor,
                     resource_type="job_posting", resource_id=job_id, after_summary=f"state={state}")
        return {"job_posting_id": job_id, "state": row.state, "notes": row.notes}

    def calculate_match(self, job, profile: dict[str, Any] | None = None,
                        profile_id: str = "default") -> dict[str, Any]:
        """确定性匹配（规范 §18）：无 AI 也能跑；结果可解释、可重算。"""
        profile = profile or default_profile()
        result = matching.score_job({
            "title": job.title, "description": job.description, "location": job.location,
            "salary_text": job.salary_text, "seniority": job.seniority,
            "published_at": job.published_at,
        }, profile)
        row = self.matches.replace(
            job_posting_id=job.id, profile_id=profile_id, score=result.score, parts=result.parts,
            reasons=result.reasons, gaps=result.gaps,
            profile_version=str(profile.get("version") or "profile-1.0.0"),
            rule_version=result.rule_version, model_version="",
            input_hash=sha256_text(json.dumps([job.title, job.description, profile], ensure_ascii=False,
                                              sort_keys=True, default=str)),
        )
        enqueue(self.session, EventEnvelope(
            event_type="job_match.calculated.v1",
            aggregate=new_aggregate("job_match", row.id),
            data={"job_posting_id": job.id, "score": row.score, "rule_version": row.rule_version},
        ))
        return {"id": row.id, "job_posting_id": job.id, "score": row.score, "parts": result.parts,
                "reasons": result.reasons, "gaps": result.gaps,
                "profile_version": row.profile_version, "rule_version": row.rule_version,
                "calculated_at": row.calculated_at}

    def create_alert(self, *, query_spec: dict[str, Any], threshold: float = 70.0,
                     delivery_channel: str = "inbox") -> dict[str, Any]:
        row = self.alerts.create(user_id=self.actor.actor_id, query_spec=query_spec,
                                 threshold=threshold, delivery_channel=delivery_channel)
        audit.record(self.session, action="job_alert.create", actor=self.actor, resource_type="job_alert",
                     resource_id=row.id, after_summary=f"threshold={threshold}")
        return _alert_out(row)

    def list_alerts(self) -> list[dict[str, Any]]:
        return [_alert_out(x) for x in self.alerts.list(user_id=self.actor.actor_id)]


# ---------------------------------------------------------------- 转换与默认值

def default_profile() -> dict[str, Any]:
    """默认候选人偏好（可被请求覆盖）。与既有 data/config 的画像保持同一口径。"""
    return {
        "version": "profile-1.0.0",
        "skills": ["渠道", "区域", "经销商", "代理商", "回款", "终端", "KA", "下沉", "家电"],
        "locations": ["河南", "郑州", "新乡", "洛阳", "开封"],
        "seniority": "manager",
        "salary_min": 12000,
        "salary_max": 18000,
        "exclude_words": ["校招", "应届", "实习", "中介", "派遣", "外包"],
    }


def _policy_of(row) -> JobSourcePolicy:
    try:
        return JobSourcePolicy(**json.loads(row.policy or "{}"))
    except Exception:  # noqa: BLE001 —— 策略损坏时按最严格处理：不许抓
        return JobSourcePolicy(domain="", allow_auto_crawl=False)


def _candidate_to_parsed(cand: RadarCandidate, *, source_key: str) -> ParsedJobPosting:
    text = " ".join([cand.title, cand.description])
    lo, hi = parse_salary_text(cand.salary_text)
    return ParsedJobPosting(
        source_key=source_key,
        external_id=cand.url or f"{cand.company_name}-{cand.title}",
        canonical_url=canonicalize_url(cand.url),
        company_name=cand.company_name,
        title=cand.title,
        location=cand.location,
        work_mode=detect_work_mode(text),
        employment_type=detect_employment_type(text),
        seniority=detect_seniority(cand.title),
        description=cand.description,
        salary_text=cand.salary_text,
        raw_ref=cand.platform or host_of(cand.url),
        confidence=0.9 if (cand.title and cand.url) else 0.4,
        extra={"evidence": cand.evidence, "salary_min": lo, "salary_max": hi},
    )


def _source_out(row) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "base_url": row.base_url, "source_type": row.source_type,
            "status": row.status, "rate_limit_per_minute": row.rate_limit_per_minute,
            "consecutive_failures": row.consecutive_failures, "blocked_reason": row.blocked_reason,
            "last_run_at": row.last_run_at, "policy": json.loads(row.policy or "{}")}


def _job_out(row, match) -> dict[str, Any]:
    parts, reasons, gaps = {}, [], []
    score = 0.0
    if match is not None:
        score = match.score
        parts = json.loads(match.parts or "{}")
        reasons = json.loads(match.reasons or "[]")
        gaps = json.loads(match.gaps or "[]")
    return {
        "id": row.id, "source_id": row.source_id, "company_id": row.company_id,
        "company_name": row.company_name, "title": row.title, "location": row.location,
        "work_mode": row.work_mode, "employment_type": row.employment_type,
        "seniority": row.seniority, "canonical_url": row.canonical_url,
        "salary_text": row.salary_text, "status": row.status, "fingerprint": row.fingerprint,
        "description": row.description, "published_at": row.published_at,
        "first_seen_at": row.first_seen_at, "last_seen_at": row.last_seen_at,
        "match": {"score": score, "parts": parts, "reasons": reasons, "gaps": gaps,
                  "rule_version": match.rule_version if match else "",
                  "calculated_at": match.calculated_at if match else None},
    }


def _alert_out(row) -> dict[str, Any]:
    return {"id": row.id, "query_spec": json.loads(row.query_spec or "{}"), "threshold": row.threshold,
            "delivery_channel": row.delivery_channel, "enabled": row.enabled}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
