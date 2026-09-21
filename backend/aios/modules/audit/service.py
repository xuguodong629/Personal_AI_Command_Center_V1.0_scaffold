"""审计服务（规范 §10）：写不可变事件；敏感正文只留脱敏摘要。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from aios.core.http import Actor
from aios.core.ids import new_uuid
from aios.core.logging import get_logger, get_request_id
from aios.modules.audit.models import AuditEvent

logger = get_logger("aios.audit")

# 规范 §10：这些动作必须生成不可变审计事件
AUDITED_ACTIONS = (
    "config.update",
    "source.create",
    "source.update",
    "source.run",
    "job_posting.import",
    "job_posting.export",
    "job_posting.state_change",
    "job_alert.create",
    "ai.invoke",
    "notification.send",
    "record.delete",
    "record.archive",
    "automation.approve",
)


def record(session: Session, *, action: str, actor: Actor | None = None,
           resource_type: str = "", resource_id: str = "",
           before_summary: str = "", after_summary: str = "",
           result: str = "ok", client_summary: str = "", extra: dict[str, Any] | None = None) -> AuditEvent:
    """写入一条审计事件（调用方负责 commit，保证与业务数据同事务）。"""
    actor = actor or Actor(actor_id="system", workspace_id="system")
    if extra:
        suffix = " " + ", ".join(f"{k}={v}" for k, v in extra.items() if v not in (None, ""))
        after_summary = (after_summary + suffix).strip()
    row = AuditEvent(
        id=new_uuid(),
        workspace_id=actor.workspace_id,
        actor_id=actor.actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before_summary=before_summary[:1000],
        after_summary=after_summary[:1000],
        request_id=get_request_id(),
        client_summary=client_summary[:120],
        result=result,
    )
    session.add(row)
    logger.info("audit_event", extra={"extra_fields": {"action": action, "resource_type": resource_type,
                                                       "resource_id": resource_id, "result": result,
                                                       "actor_id": actor.actor_id}})
    return row


def list_events(session: Session, *, action: str = "", resource_type: str = "",
                limit: int = 50) -> list[AuditEvent]:
    q = session.query(AuditEvent)
    if action:
        q = q.filter(AuditEvent.action == action)
    if resource_type:
        q = q.filter(AuditEvent.resource_type == resource_type)
    return q.order_by(AuditEvent.created_at.desc()).limit(max(1, min(200, limit))).all()
