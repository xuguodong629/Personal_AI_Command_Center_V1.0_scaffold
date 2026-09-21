"""错误模型（规范 §9.3）：稳定可枚举的错误码 + 统一 HTTP 映射；绝不外泄堆栈/SQL/密钥。"""
from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """可枚举错误码（规范 §9.3）。"""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # JIC / 来源准入（规范 §14.1）
    JOB_SOURCE_NOT_ALLOWED = "JOB_SOURCE_NOT_ALLOWED"
    JOB_SOURCE_DISABLED = "JOB_SOURCE_DISABLED"
    JOB_SOURCE_BLOCKED = "JOB_SOURCE_BLOCKED"
    JOB_SOURCE_BUDGET_EXHAUSTED = "JOB_SOURCE_BUDGET_EXHAUSTED"
    PARSE_CONFIDENCE_TOO_LOW = "PARSE_CONFIDENCE_TOO_LOW"
    # AI（规范 §21）
    AI_SCHEMA_INVALID = "AI_SCHEMA_INVALID"
    AI_PROVIDER_UNAVAILABLE = "AI_PROVIDER_UNAVAILABLE"
    AI_BUDGET_EXCEEDED = "AI_BUDGET_EXCEEDED"


_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.JOB_SOURCE_NOT_ALLOWED: 403,
    ErrorCode.JOB_SOURCE_DISABLED: 409,
    ErrorCode.JOB_SOURCE_BLOCKED: 409,
    ErrorCode.JOB_SOURCE_BUDGET_EXHAUSTED: 429,
    ErrorCode.PARSE_CONFIDENCE_TOO_LOW: 422,
    ErrorCode.AI_SCHEMA_INVALID: 502,
    ErrorCode.AI_PROVIDER_UNAVAILABLE: 503,
    ErrorCode.AI_BUDGET_EXCEEDED: 429,
}


class AIOSError(Exception):
    """业务异常基类：携带错误码、可读信息与字段级细节。

    `retryable` 标记传输类瞬时错误（超时、限流、5xx）——作业与 AI Gateway 据此决定是否退避重试；
    业务错误（校验失败、策略禁止、Schema 不合格）必须保持 False，**不允许被静默重试或降级**（规范 §21.2）。
    """

    def __init__(self, code: ErrorCode, message: str,
                 details: list[dict[str, Any]] | None = None, status: int | None = None,
                 retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []
        self.status = status or _STATUS_BY_CODE.get(code, 500)
        self.retryable = retryable

    def to_error(self, request_id: str = "") -> dict[str, Any]:
        return {"error": {"code": self.code.value, "message": self.message,
                          "details": self.details, "request_id": request_id}}


class NotFoundError(AIOSError):
    def __init__(self, resource: str, resource_id: str = "") -> None:
        super().__init__(ErrorCode.NOT_FOUND, f"{resource} 不存在",
                         [{"field": "id", "reason": resource_id}] if resource_id else [])


class ValidationError(AIOSError):
    def __init__(self, message: str, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(ErrorCode.VALIDATION_ERROR, message, details)


class SourceNotAllowedError(AIOSError):
    def __init__(self, source_url: str = "", reason: str = "not_allowed") -> None:
        super().__init__(ErrorCode.JOB_SOURCE_NOT_ALLOWED, "该来源未被允许采集",
                         [{"field": "source_url", "reason": reason}] if source_url else
                         [{"field": "source", "reason": reason}])
