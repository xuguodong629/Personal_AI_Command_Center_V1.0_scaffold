"""JIC API（规范 §17）：职位、来源、采集运行、提醒；权限按能力校验。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from aios.contracts import JobSourcePolicy, RadarCandidate
from aios.core.db import get_session
from aios.core.http import Actor, ok, paginated, require
from aios.modules.jic.application import JICService

router = APIRouter(tags=["jic"])


# ---------------------------------------------------------------- 请求模型

class ImportRequest(BaseModel):
    source_id: str | None = None
    source_key: str = "radar"
    candidates: list[RadarCandidate] = Field(default_factory=list)
    note: str = ""


class StateRequest(BaseModel):
    state: str
    notes: str = ""


class SourceCreateRequest(BaseModel):
    name: str
    base_url: str = ""
    source_type: str = "public_html"
    status: str = "enabled"
    policy: JobSourcePolicy


class SourceUpdateRequest(BaseModel):
    status: str = ""
    policy: JobSourcePolicy | None = None


class RunSourceRequest(BaseModel):
    trigger: str = "manual"
    settings: dict[str, Any] = Field(default_factory=dict)


class AlertCreateRequest(BaseModel):
    query_spec: dict[str, Any] = Field(default_factory=dict)
    threshold: float = 70.0
    delivery_channel: str = "inbox"


# ---------------------------------------------------------------- 职位

@router.get("/job-postings")
def list_job_postings(
    q: str = Query(default=""), company_id: str = Query(default=""), location: str = Query(default=""),
    work_mode: str = Query(default=""), employment_type: str = Query(default=""),
    seniority: str = Query(default=""), status: str = Query(default="active"),
    source_id: str = Query(default=""), page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session), actor: Actor = Depends(require("read")),
) -> dict[str, Any]:
    """分页 + 稳定排序 + 过滤白名单（规范 §9.1/§17）。"""
    service = JICService(session, actor)
    items, total = service.list_jobs(q=q, company_id=company_id, location=location, work_mode=work_mode,
                                     employment_type=employment_type, seniority=seniority, status=status,
                                     source_id=source_id, page=page, page_size=page_size)
    return paginated(items, page=page, page_size=page_size, total=total,
                     sort="first_seen_at desc, id asc")


@router.get("/job-postings/{job_id}")
def get_job_posting(job_id: str, session: Session = Depends(get_session),
                    actor: Actor = Depends(require("read"))) -> dict[str, Any]:
    return ok(JICService(session, actor).get_job(job_id))


@router.post("/job-postings/import")
def import_job_postings(req: ImportRequest, session: Session = Depends(get_session),
                        actor: Actor = Depends(require("write"))) -> dict[str, Any]:
    """导入用户粘贴的链接/文本（规范 §14 模块输入）。"""
    service = JICService(session, actor)
    stats = service.import_candidates(req.candidates, source_id=req.source_id,
                                      source_key=req.source_key, actor_note=req.note)
    session.commit()
    return ok(stats)


@router.patch("/job-postings/{job_id}/state")
def set_job_state(job_id: str, req: StateRequest, session: Session = Depends(get_session),
                  actor: Actor = Depends(require("write"))) -> dict[str, Any]:
    payload = JICService(session, actor).set_state(job_id, state=req.state, notes=req.notes)
    session.commit()
    return ok(payload)


@router.get("/job-postings/{job_id}/matches")
def get_job_matches(job_id: str, session: Session = Depends(get_session),
                    actor: Actor = Depends(require("read"))) -> dict[str, Any]:
    payload = JICService(session, actor).get_job(job_id)
    return ok(payload.get("match") or {})


# ---------------------------------------------------------------- 来源与采集

@router.get("/job-sources")
def list_job_sources(status: str = Query(default=""), session: Session = Depends(get_session),
                     actor: Actor = Depends(require("admin"))) -> dict[str, Any]:
    return ok(JICService(session, actor).list_sources(status=status))


@router.get("/job-sources/health")
def job_sources_health(session: Session = Depends(get_session),
                       actor: Actor = Depends(require("admin"))) -> dict[str, Any]:
    return ok(JICService(session, actor).source_health())


@router.post("/job-sources")
def create_job_source(req: SourceCreateRequest, session: Session = Depends(get_session),
                      actor: Actor = Depends(require("admin"))) -> dict[str, Any]:
    payload = JICService(session, actor).create_source(
        name=req.name, base_url=req.base_url, source_type=req.source_type,
        policy=req.policy, status=req.status)
    session.commit()
    return ok(payload)


@router.patch("/job-sources/{source_id}")
def update_job_source(source_id: str, req: SourceUpdateRequest,
                      session: Session = Depends(get_session),
                      actor: Actor = Depends(require("admin"))) -> dict[str, Any]:
    payload = JICService(session, actor).update_source(source_id, status=req.status, policy=req.policy)
    session.commit()
    return ok(payload)


@router.post("/job-sources/{source_id}/runs")
def run_job_source(source_id: str, req: RunSourceRequest = Body(default=RunSourceRequest()),
                   session: Session = Depends(get_session),
                   actor: Actor = Depends(require("run"))) -> dict[str, Any]:
    """请求一次受控采集（规范 §17：run 权限）。准入不通过即拒绝，不发起网络请求。"""
    payload = JICService(session, actor).run_source(source_id, trigger=req.trigger, settings=req.settings)
    session.commit()
    return ok(payload)


@router.get("/crawl-runs/{run_id}")
def get_crawl_run(run_id: str, session: Session = Depends(get_session),
                  actor: Actor = Depends(require("read"))) -> dict[str, Any]:
    from aios.core.errors import NotFoundError
    from aios.modules.jic.infrastructure.repositories import CrawlRepository
    row = CrawlRepository(session).get_run(run_id)
    if row is None:
        raise NotFoundError("采集运行", run_id)
    import json as _json
    return ok({"id": row.id, "source_id": row.source_id, "trigger": row.trigger, "status": row.status,
               "started_at": row.started_at, "finished_at": row.finished_at,
               "stats": _json.loads(row.stats or "{}"), "error_code": row.error_code,
               "error_message": row.error_message})


# ---------------------------------------------------------------- 提醒

@router.post("/job-alerts")
def create_job_alert(req: AlertCreateRequest, session: Session = Depends(get_session),
                     actor: Actor = Depends(require("write"))) -> dict[str, Any]:
    payload = JICService(session, actor).create_alert(query_spec=req.query_spec, threshold=req.threshold,
                                                      delivery_channel=req.delivery_channel)
    session.commit()
    return ok(payload)


@router.get("/job-alerts")
def list_job_alerts(session: Session = Depends(get_session),
                    actor: Actor = Depends(require("read"))) -> dict[str, Any]:
    return ok(JICService(session, actor).list_alerts())
