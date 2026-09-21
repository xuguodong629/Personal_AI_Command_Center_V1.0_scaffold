"""结构化日志（规范 §22.1）：JSON 行、携带 request_id / trace_id，禁止记录敏感正文。"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from aios.core.config import get_settings

_request_id: ContextVar[str] = ContextVar("aios_request_id", default="")
_trace_id: ContextVar[str] = ContextVar("aios_trace_id", default="")

_SENSITIVE_KEYS = ("api_key", "token", "password", "cookie", "authorization", "secret", "id_card", "phone")


def set_request_context(request_id: str, trace_id: str) -> None:
    _request_id.set(request_id)
    _trace_id.set(trace_id)


def get_request_id() -> str:
    return _request_id.get()


def get_trace_id() -> str:
    return _trace_id.get()


def _redact(value: Any) -> Any:
    """输出脱敏（规范 §23.6 / 附录 B）：密钥、Cookie、PII 不进日志。"""
    if isinstance(value, dict):
        return {k: ("***" if any(s in k.lower() for s in _SENSITIVE_KEYS) else _redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    """每条日志一行 JSON，字段：timestamp/level/service/environment/message/request_id/trace_id。"""

    def format(self, record: logging.LogRecord) -> str:
        settings = get_settings()
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "service": settings.otel.service_name,
            "environment": settings.app.env,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
            "trace_id": get_trace_id(),
        }
        for key in ("actor_id", "workspace_id", "source_id", "provider", "path", "method",
                    "status_code", "duration_ms", "job_execution_id", "error_code"):
            value = getattr(record, key, None)
            if value not in (None, ""):
                payload[key] = value
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(_redact(extra))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)[:2000]
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    """统一日志器（规范 §22.1：禁止 print 作为生产日志）。"""
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, settings.app.log_level.upper(), logging.INFO))
    # uvicorn 访问日志也走同一格式，避免文本/JSON 混杂
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_extra(**fields: Any) -> dict[str, Any]:
    """用法：logger.info("msg", extra=log_extra(source_id=sid))。"""
    return {"extra_fields": fields}
