"""作业 API（规范 §5/§19/§24）：提交即返回作业卡片，长任务在后台执行。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from aios.core.db import get_session
from aios.core.errors import NotFoundError
from aios.core.http import Actor, ok, paginated, require
from aios.modules.jobs import runner
from aios.modules.jobs.models import JobExecution

router = APIRouter(prefix="/jobs", tags=["jobs"])


class SubmitJobRequest(BaseModel):
    job_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = ""
    queue: str = "default"
    max_attempts: int = 3


def _job_card(row: JobExecution, reused: bool = False) -> dict[str, Any]:
    """作业卡片（规范 §24：排队/运行/成功/失败 + 可读错误）。"""
    return {
        "id": row.id,
        "job_type": row.job_type,
        "status": row.status,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "queue": row.queue,
        "trace_id": row.trace_id,
        "idempotency_key": row.idempotency_key,
        "queued_at": row.queued_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "reused": reused,
    }


@router.get("/types")
def list_types(_: Actor = Depends(require("read"))) -> dict[str, Any]:
    return ok(runner.registered_types())


@router.post("")
def submit_job(req: SubmitJobRequest,
               idempotency_header: str = Header(default="", alias="Idempotency-Key"),
               session: Session = Depends(get_session),
               actor: Actor = Depends(require("run"))) -> dict[str, Any]:
    """提交长任务；同 `Idempotency-Key` 重复提交返回同一作业（规范 §9.1）。"""
    key = idempotency_header.strip() or req.idempotency_key.strip()
    row, reused = runner.submit(
        session, job_type=req.job_type, payload=req.payload,
        actor_id=actor.actor_id, workspace_id=actor.workspace_id,
        idempotency_key=key, queue=req.queue, max_attempts=req.max_attempts,
    )
    session.commit()
    if not reused:
        runner.dispatch(row.id)
    return ok(_job_card(row, reused))


@router.get("")
def list_jobs(status: str = Query(default=""), job_type: str = Query(default=""),
              page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
              session: Session = Depends(get_session),
              _: Actor = Depends(require("read"))) -> dict[str, Any]:
    q = session.query(JobExecution)
    if status:
        q = q.filter(JobExecution.status == status)
    if job_type:
        q = q.filter(JobExecution.job_type == job_type)
    total = q.count()
    rows = (q.order_by(JobExecution.queued_at.desc().nullslast())
            .offset((page - 1) * page_size).limit(page_size).all())
    return paginated([_job_card(r) for r in rows], page=page, page_size=page_size, total=total)


@router.get("/{job_id}")
def get_job(job_id: str, session: Session = Depends(get_session),
            _: Actor = Depends(require("read"))) -> dict[str, Any]:
    row = session.get(JobExecution, job_id)
    if row is None:
        raise NotFoundError("作业", job_id)
    return ok(_job_card(row))


@router.post("/{job_id}/replay")
def replay_job(job_id: str, session: Session = Depends(get_session),
               actor: Actor = Depends(require("approve"))) -> dict[str, Any]:
    """死信重放（规范 §19.3）：**必须生成新的执行记录**，不复用旧记录。"""
    row = session.get(JobExecution, job_id)
    if row is None:
        raise NotFoundError("作业", job_id)
    import json as _json
    new_row, _ = runner.submit(
        session, job_type=row.job_type, payload=_json.loads(row.input_ref or "{}"),
        actor_id=actor.actor_id, workspace_id=actor.workspace_id,
        idempotency_key=f"replay-of-{row.id}-{datetime.now().timestamp():.0f}",
        queue=row.queue, max_attempts=row.max_attempts,
    )
    session.commit()
    runner.dispatch(new_row.id)
    return ok(_job_card(new_row))
