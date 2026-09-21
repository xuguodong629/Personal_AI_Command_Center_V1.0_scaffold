"""作业执行（规范 §5 / §19）：API 只入队，常驻 worker 领取并执行。

为什么不引入 Celery（见 docs/adr）：单机本地优先场景下，用「`job_executions` 表 + 常驻 worker 线程」即可获得
同等语义——状态机、幂等键、尝试次数、指数退避、死信、中断恢复与 trace 关联；且不新增运行依赖。
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from aios.core.db import session_scope
from aios.core.errors import AIOSError, ErrorCode
from aios.core.ids import new_uuid
from aios.core.logging import get_logger, get_trace_id, log_extra, set_request_context
from aios.modules.jobs.models import JobExecution

logger = get_logger("aios.jobs")

JobHandler = Callable[[Session, dict[str, Any]], dict[str, Any]]
_HANDLERS: dict[str, JobHandler] = {}

# 退避（规范 §19.3：带抖动的指数退避；可按环境覆盖）
RETRY_DELAYS_SECONDS: tuple[float, ...] = (5.0, 30.0, 120.0, 600.0)
TERMINAL_STATUSES = ("succeeded", "failed", "dead")
# 崩溃恢复：running 超过该时长视为孤儿作业，重新排队（规范 §19.3 中断恢复）
STALE_RUNNING_SECONDS = 600


def register(job_type: str) -> Callable[[JobHandler], JobHandler]:
    """注册作业处理器（模块注册点，规范 §30.3）。"""

    def _decorator(fn: JobHandler) -> JobHandler:
        _HANDLERS[job_type] = fn
        return fn

    return _decorator


def registered_types() -> list[str]:
    return sorted(_HANDLERS)


def submit(session: Session, *, job_type: str, payload: dict[str, Any], actor_id: str = "",
           workspace_id: str = "", idempotency_key: str = "", queue: str = "default",
           max_attempts: int = 3, input_ref: str | None = None) -> tuple[JobExecution, bool]:
    """创建作业（只入队，不执行）。返回 (作业, 是否复用已有)。

    幂等（规范 §9.1/§13）：同一 `job_type + idempotency_key` 已存在时直接返回既有作业。
    """
    if job_type not in _HANDLERS:
        raise AIOSError(ErrorCode.VALIDATION_ERROR, f"未注册的作业类型：{job_type}",
                        [{"field": "job_type", "reason": "unknown",
                          "registered": registered_types()}])
    key = idempotency_key.strip()
    if key:
        existing = (session.query(JobExecution)
                    .filter(JobExecution.job_type == job_type, JobExecution.idempotency_key == key)
                    .one_or_none())
        if existing is not None:
            return existing, True
    now = datetime.now(timezone.utc)
    row = JobExecution(
        id=new_uuid(),
        job_type=job_type,
        idempotency_key=key,
        status="queued",
        attempts=0,
        max_attempts=max(1, max_attempts),
        trace_id=get_trace_id(),
        actor_id=actor_id,
        workspace_id=workspace_id,
        input_ref=input_ref if input_ref is not None else json.dumps(payload, ensure_ascii=False),
        queue=queue,
        queued_at=now,
        next_attempt_at=now,
    )
    session.add(row)
    session.flush()
    return row, False


def claim_due(session: Session, *, limit: int = 5) -> list[str]:
    """领取到期作业（queued / retrying），并把它们标记为 running。

    同时回收孤儿 `running`（进程崩溃或中断）：超过 `STALE_RUNNING_SECONDS` 的重新排队。
    """
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=STALE_RUNNING_SECONDS)
    orphans = (session.query(JobExecution)
               .filter(JobExecution.status == "running", JobExecution.started_at < stale_before)
               .all())
    for row in orphans:
        row.status = "retrying"
        row.next_attempt_at = now
        logger.warning("job_reclaimed", extra=log_extra(job_execution_id=row.id))
    if orphans:
        session.flush()

    rows = (session.query(JobExecution)
            .filter(JobExecution.status.in_(("queued", "retrying")),
                    JobExecution.next_attempt_at.is_not(None),
                    JobExecution.next_attempt_at <= now)
            .order_by(JobExecution.next_attempt_at)
            .limit(max(1, limit)).all())
    ids: list[str] = []
    for row in rows:
        row.status = "running"
        row.started_at = now
        row.attempts += 1
        row.next_attempt_at = None
        ids.append(row.id)
    session.flush()
    return ids


def execute(job_id: str) -> None:
    """执行一个已领取的作业（在工作线程内、独立会话中运行）。"""
    with session_scope() as session:
        row = session.get(JobExecution, job_id)
        if row is None or row.status != "running":
            return
        job_type = row.job_type
        trace_id = row.trace_id
        attempt = row.attempts
        max_attempts = row.max_attempts
        payload = _safe_json(row.input_ref) or {}
    # 后台作业没有 HTTP 请求：用作业 ID 作为 request_id，保证审计与日志可关联（规范 §10/§22.1）
    set_request_context(f"job_{job_id}", trace_id)
    handler = _HANDLERS.get(job_type)
    if handler is None:
        _finish(job_id, status="dead", error_code="HANDLER_MISSING",
                error_message=f"未注册的作业类型：{job_type}")
        return
    try:
        result = _run_handler(handler, payload)
    except Exception as exc:  # noqa: BLE001 —— 作业边界必须兜住一切异常并落库
        exhausted = attempt >= max_attempts
        delay = RETRY_DELAYS_SECONDS[min(attempt - 1, len(RETRY_DELAYS_SECONDS) - 1)]
        _finish(job_id, status="dead" if exhausted else "retrying",
                error_code=type(exc).__name__, error_message=f"{exc}"[:2000],
                next_attempt_at=None if exhausted else datetime.now(timezone.utc) + timedelta(seconds=delay))
        logger.warning("job_failed", extra=log_extra(job_execution_id=job_id, job_type=job_type,
                                                     error_code=type(exc).__name__, attempts=attempt,
                                                     exhausted=exhausted))
        return
    _finish(job_id, status="succeeded", output_ref=json.dumps(result, ensure_ascii=False)[:20000])
    logger.info("job_succeeded", extra=log_extra(job_execution_id=job_id, job_type=job_type))


def _finish(job_id: str, *, status: str, output_ref: str = "", error_code: str = "",
            error_message: str = "", next_attempt_at: datetime | None = None) -> None:
    with session_scope() as session:
        row = session.get(JobExecution, job_id)
        if row is None:
            return
        row.status = status
        row.error_code = error_code
        row.error_message = error_message
        row.next_attempt_at = next_attempt_at
        if output_ref:
            row.output_ref = output_ref
        if status in TERMINAL_STATUSES:
            row.finished_at = datetime.now(timezone.utc)


def _run_handler(handler: JobHandler, payload: dict[str, Any]) -> dict[str, Any]:
    """在工作线程里跑同步处理器，使用独立会话（不可跨线程复用 Session）。"""
    with session_scope() as session:
        return handler(session, payload)


def _safe_json(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def dispatch(job_id: str) -> None:
    """兼容旧调用：把作业标记为"立即到期"，由常驻 worker 领取（不再用 create_task）。"""
    with session_scope() as session:
        row = session.get(JobExecution, job_id)
        if row is not None and row.status in ("queued", "retrying"):
            row.next_attempt_at = datetime.now(timezone.utc)


async def run_once(limit: int = 5) -> int:
    """执行一批到期作业（供 worker 与测试复用）。返回本次执行条数。"""
    with session_scope() as session:
        ids = claim_due(session, limit=limit)
    for job_id in ids:
        await asyncio.to_thread(execute, job_id)
    return len(ids)
