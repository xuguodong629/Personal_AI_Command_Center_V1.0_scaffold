"""作业处理器注册（规范 §30.3 注册点）：长任务在此注册，由 jobs API 异步执行。"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from aios.contracts import RadarCandidate
from aios.core.http import Actor
from aios.core.logging import get_logger
from aios.core.outbox import mark_published, take_unpublished
from aios.modules.jic.application import JICService
from aios.modules.jobs.runner import register

logger = get_logger("aios.handlers")


@register("jic.import_candidates")
def import_candidates(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """把候选岗位导入 JIC（雷达/手工粘贴共用）。"""
    candidates = [RadarCandidate(**row) for row in (payload.get("candidates") or [])]
    actor = Actor(actor_id=payload.get("actor_id") or "local-user",
                  workspace_id=payload.get("workspace_id") or "local-workspace")
    service = JICService(session, actor)
    return service.import_candidates(candidates, source_id=payload.get("source_id"),
                                     source_key=payload.get("source_key") or "radar",
                                     actor_note=payload.get("note") or "job:import_candidates")


@register("jic.run_source")
def run_source(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """受控采集一个来源（准入不通过会抛错并落死信）。"""
    actor = Actor(actor_id=payload.get("actor_id") or "local-user",
                  workspace_id=payload.get("workspace_id") or "local-workspace")
    service = JICService(session, actor)
    body = str(payload.get("body") or "")
    _ = body
    return service.run_source(str(payload.get("source_id") or ""),
                              trigger=str(payload.get("trigger") or "job"),
                              settings=payload.get("settings") or {})


@register("platform.publish_outbox")
def publish_outbox(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Outbox 发布器（规范 §13）：把事件标记为已发布并记录条数。"""
    rows = take_unpublished(session, limit=int(payload.get("limit") or 50))
    for row in rows:
        # 本切片没有独立消息总线：发布即"投递到进程内消费者"，此处只做状态流转与计数。
        logger.info("outbox_publish", extra={"extra_fields": {"event_type": row.event_type,
                                                              "aggregate_id": row.aggregate_id}})
        mark_published(session, row.id)
    return {"published": len(rows),
            "types": sorted({r.event_type for r in rows})}


@register("jic.recalculate_matches")
def recalculate_matches(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """按给定画像重算匹配（规范 §18：匹配可重算）。"""
    from aios.modules.jic.infrastructure.repositories import JobPostingRepository
    actor = Actor(actor_id=payload.get("actor_id") or "local-user",
                  workspace_id=payload.get("workspace_id") or "local-workspace")
    service = JICService(session, actor)
    profile = payload.get("profile") or None
    limit = int(payload.get("limit") or 200)
    jobs, _ = JobPostingRepository(session).list(status="active", page=1, page_size=limit)
    scores: list[float] = []
    for job in jobs:
        result = service.calculate_match(job, profile)
        scores.append(float(result["score"]))
    return {"recalculated": len(scores),
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
            "profile_version": (profile or {}).get("version", "profile-1.0.0")}


def payload_from_json(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
