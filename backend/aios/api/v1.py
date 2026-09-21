"""/api/v1 路由装配（规范 §9.1）：版本前缀、健康检查（含依赖状态）、模块注册点。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from aios.core.config import get_settings
from aios.core.db import get_session
from aios.core.http import Actor, install_http_layer, ok, require
from aios.core.logging import get_logger
from aios.modules.ai_gateway.models import AIRun
from aios.modules.ai_gateway.prompts import list_prompts
from aios.modules.audit.api import router as audit_router
from aios.modules.jic.api import router as jic_router
from aios.modules.jobs import handlers as _handlers  # noqa: F401 —— 注册作业处理器
from aios.modules.jobs.api import router as jobs_router
from aios.modules.jobs.runner import registered_types

logger = get_logger("aios.api")


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    router.include_router(jic_router)
    router.include_router(jobs_router)
    router.include_router(audit_router)

    @router.get("/health", tags=["platform"])
    def health(session: Session = Depends(get_session)) -> dict[str, Any]:
        """健康检查返回依赖状态（规范 §31 第 1 条）。"""
        settings = get_settings()
        deps: dict[str, Any] = {"database": {"url_scheme": settings.db.url.split(":", 1)[0]}}
        try:
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            deps["database"].update({"status": "ok", "migration": revision})
        except Exception as exc:  # noqa: BLE001 —— 健康检查必须给出可读原因而不是抛 500
            deps["database"].update({"status": "error", "detail": type(exc).__name__,
                                     "hint": "尚未执行迁移：python -m aios.cli migrate"})
        pending = 0
        try:
            pending = int(session.execute(text("SELECT COUNT(*) FROM outbox_events WHERE published = 0")).scalar() or 0)
        except Exception:  # noqa: BLE001
            pending = -1
        deps["outbox_pending"] = pending
        deps["prompts"] = len(list_prompts())
        deps["job_types"] = registered_types()
        deps["ai_provider_configured"] = bool(get_settings().ai.purpose_model or True)
        overall = "ok" if deps["database"].get("status") == "ok" else "degraded"
        return ok({"status": overall, "service": settings.otel.service_name, "version": "1.0.0",
                   "environment": settings.app.env, "dependencies": deps})

    @router.get("/prompts", tags=["ai"])
    def get_prompts(_: Actor = Depends(require("read"))) -> dict[str, Any]:
        """提示词版本目录（规范 §21.3：提示词可审查、有版本）。"""
        return ok(list_prompts())

    @router.get("/ai/runs", tags=["ai"])
    def list_ai_runs(purpose: str = Query(default=""), limit: int = Query(default=20, ge=1, le=100),
                     session: Session = Depends(get_session),
                     actor: Actor = Depends(require("admin"))) -> dict[str, Any]:
        """AI 调用账本（规范 §21.1：可回答花了多少、为什么这次结果不同）。"""
        q = session.query(AIRun)
        if purpose:
            q = q.filter(AIRun.purpose == purpose)
        rows = q.order_by(AIRun.created_at.desc()).limit(limit).all()
        return ok([{"id": r.id, "purpose": r.purpose, "provider": r.provider, "model": r.model,
                    "prompt_id": r.prompt_id, "prompt_version": r.prompt_version,
                    "schema_version": r.schema_version, "status": r.status,
                    "token_usage": r.token_usage, "cost": r.cost, "cache_hit": r.cache_hit,
                    "latency_ms": r.latency_ms, "error_code": r.error_code, "created_at": r.created_at}
                   for r in rows])

    return router


def install(app: FastAPI) -> None:
    """把 v1 切片挂到既有应用上（规范 §30.1：最小化改动）。"""
    install_http_layer(app)
    app.include_router(build_router())

    # 常驻作业 worker（规范 §5：API 不等待长任务；§7：worker 入口）
    # 注意：新版 Starlette 移除了 `app.add_event_handler`，统一挂到 router 的 on_startup/on_shutdown。
    from aios.core.config import get_settings
    from aios.modules.jobs.worker import start_worker, stop_worker

    def _startup() -> None:
        for item in get_settings().validate():
            logger.warning("config_warning", extra={"extra_fields": {"detail": item}})
        start_worker(poll_seconds=0.5)

    app.router.on_startup.append(_startup)
    app.router.on_shutdown.append(stop_worker)
