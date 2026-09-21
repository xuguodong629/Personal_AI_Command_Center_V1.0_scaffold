"""审计与作业查询 API（规范 §10：审计可查；§24：作业卡片可见）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aios.core.db import get_session
from aios.core.http import Actor, ok, require
from aios.modules.audit import service as audit

router = APIRouter(prefix="/audit-events", tags=["audit"])


def _out(row) -> dict[str, Any]:
    return {"id": row.id, "workspace_id": row.workspace_id, "actor_id": row.actor_id,
            "action": row.action, "resource_type": row.resource_type, "resource_id": row.resource_id,
            "before_summary": row.before_summary, "after_summary": row.after_summary,
            "request_id": row.request_id, "result": row.result, "created_at": row.created_at}


@router.get("")
def list_audit_events(action: str = Query(default=""), resource_type: str = Query(default=""),
                      limit: int = Query(default=50, ge=1, le=200),
                      session: Session = Depends(get_session),
                      actor: Actor = Depends(require("admin"))) -> dict[str, Any]:
    rows = audit.list_events(session, action=action, resource_type=resource_type, limit=limit)
    return ok([_out(x) for x in rows])


@router.get("/actions")
def list_audited_actions(_: Actor = Depends(require("read"))) -> dict[str, Any]:
    return ok(list(audit.AUDITED_ACTIONS))
