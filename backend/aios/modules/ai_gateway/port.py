"""AIService 端口（规范 §6.2.6 / §21）：Application 层只依赖本协议，不依赖任何厂商 SDK。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class AIContext:
    """调用上下文（审计与账本用）。禁止放密钥与 PII。"""

    purpose: str = "generic"
    actor_id: str = ""
    workspace_id: str = ""
    trace_id: str = ""
    prompt_id: str = ""
    prompt_version: str = ""
    schema_version: str = ""


@dataclass
class AIOptions:
    temperature: float = 0.2
    max_tokens: int = 2048
    timeout_seconds: float = 120.0
    max_retries: int = 2
    allow_cache: bool = True


@dataclass
class AIResult:
    output: Any = None
    provider: str = ""
    model: str = ""
    token_usage: int = 0
    cost: float = 0.0
    cache_hit: bool = False
    latency_ms: int = 0
    raw_text: str = ""
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class AIService(Protocol):
    """业务模块唯一可见的 AI 能力入口（规范 §21）。"""

    capabilities: set[str]

    async def generate_structured(self, *, purpose: str, prompt: PromptLike, schema: type[T],
                                  options: AIOptions, context: AIContext) -> AIResult: ...

    async def embed(self, *, texts: list[str], model: str = "") -> list[list[float]]: ...


class PromptLike(Protocol):
    id: str
    version: str
    system: str
    template: str

    def render(self, **variables: Any) -> str: ...
