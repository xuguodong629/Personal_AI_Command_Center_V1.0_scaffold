"""标识符（规范 §9.1）：UUID 主键 + 请求 ID + trace ID。"""
from __future__ import annotations

import uuid


def new_uuid() -> str:
    """业务主键：UUID 字符串（数据库列类型为 Uuid）。"""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """形如 req_01J...；对外返回在响应 meta 与错误体里。"""
    return f"req_{uuid.uuid4().hex[:24]}"


def new_trace_id() -> str:
    return f"trace_{uuid.uuid4().hex[:24]}"


def new_event_id() -> str:
    return str(uuid.uuid4())
