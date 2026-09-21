"""HTTP 层通用件（规范 §9.2/§9.3/§10/§22）：响应封装、请求 ID、错误映射、鉴权与能力校验。"""
from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from aios.core.config import get_settings
from aios.core.errors import AIOSError, ErrorCode
from aios.core.ids import new_request_id, new_trace_id
from aios.core.logging import get_logger, get_request_id, log_extra, set_request_context

logger = get_logger("aios.http")


# ---------------------------------------------------------------- 响应封装

def ok(data: Any, request_id: str = "", **meta: Any) -> dict[str, Any]:
    """成功响应：`{data, meta{request_id,...}}`（规范 §9.2）。"""
    payload_meta: dict[str, Any] = {"request_id": request_id or get_request_id()}
    payload_meta.update({k: v for k, v in meta.items() if v is not None})
    return {"data": data, "meta": payload_meta}


def paginated(items: list[Any], *, page: int, page_size: int, total: int,
              request_id: str = "", **meta: Any) -> dict[str, Any]:
    return ok(items, request_id=request_id, page=page, page_size=page_size, total=total, **meta)


# ---------------------------------------------------------------- 鉴权（规范 §10）

@dataclass
class Actor:
    """请求主体。actor_id / workspace_id 是一等字段，为未来多用户预留。"""

    actor_id: str
    workspace_id: str
    capabilities: set[str] = field(default_factory=lambda: {"read", "write", "run", "approve", "admin"})

    def can(self, capability: str) -> bool:
        return capability in self.capabilities


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def current_actor(
    request: Request,
    x_aios_token: str = Header(default="", alias="X-AIOS-Token"),
    authorization: str = Header(default=""),
) -> Actor:
    """解析请求主体。

    - `AUTH_REQUIRED=true`：必须带令牌，且其 SHA-256 与 `AUTH_TOKEN_SHA256` 匹配（只存哈希）。
    - `AUTH_REQUIRED=false`：仅允许本机回环访问（规范 §10 的最低要求是单用户本地账户；
      关闭鉴权仅用于本机开发，见 docs/adr）。
    """
    settings = get_settings()
    token = x_aios_token.strip() or authorization.removeprefix("Bearer ").strip()
    if settings.auth.required:
        if not token:
            raise AIOSError(ErrorCode.UNAUTHENTICATED, "缺少访问令牌（X-AIOS-Token）")
        if _token_hash(token) != settings.auth.token_sha256:
            raise AIOSError(ErrorCode.UNAUTHENTICATED, "令牌无效")
    else:
        client_host = (request.client.host if request.client else "") or ""
        if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise AIOSError(ErrorCode.FORBIDDEN, "未开启鉴权时仅允许本机访问；请设置 AUTH_REQUIRED=true")
    return Actor(actor_id=settings.auth.default_actor, workspace_id=settings.auth.default_workspace)


def require(capability: str) -> Callable[..., Awaitable[Actor]]:
    """能力校验依赖（规范 §10：read/write/run/approve/admin）。"""

    async def _dep(actor: Actor = Depends(current_actor)) -> Actor:
        if not actor.can(capability):
            raise AIOSError(ErrorCode.FORBIDDEN, f"缺少能力：{capability}")
        return actor

    return _dep


# ---------------------------------------------------------------- 中间件

class RequestContextMiddleware(BaseHTTPMiddleware):
    """请求 ID + 访问日志（规范 §22.1）。trace_id 目前由本进程生成，OTel 启用后可透传。"""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or new_request_id()
        trace_id = new_trace_id()
        set_request_context(request_id, trace_id)
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Trace-Id"] = trace_id
        logger.info("request", extra=log_extra(path=request.url.path, method=request.method,
                                               status_code=response.status_code, duration_ms=duration_ms))
        return response


# ---------------------------------------------------------------- 错误映射

def install_error_handlers(app: FastAPI) -> None:
    """统一错误体（规范 §9.3）：不外泄堆栈、SQL 与密钥。"""

    @app.exception_handler(AIOSError)
    async def _aios_error(_: Request, exc: AIOSError) -> JSONResponse:
        logger.warning("business_error", extra=log_extra(error_code=exc.code.value, message=exc.message))
        return JSONResponse(status_code=exc.status, content=exc.to_error(get_request_id()))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"field": ".".join(str(x) for x in err.get("loc", [])), "reason": err.get("msg", "")}
                   for err in exc.errors()]
        err = AIOSError(ErrorCode.VALIDATION_ERROR, "请求字段校验失败", details)
        return JSONResponse(status_code=err.status, content=err.to_error(get_request_id()))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_error", exc_info=exc, extra=log_extra(error_code=ErrorCode.INTERNAL_ERROR.value))
        err = AIOSError(ErrorCode.INTERNAL_ERROR, "服务内部错误，请查看服务端日志")
        return JSONResponse(status_code=err.status, content=err.to_error(get_request_id()))


def install_http_layer(app: FastAPI) -> None:
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
