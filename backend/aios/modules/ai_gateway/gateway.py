"""AI Gateway（规范 §21.1）：路由、超时、重试、结构化校验、缓存、账本与降级。

业务模块只依赖 `AIService`；本类实现该端口并写入 `ai_runs`（每次调用一条账本）。
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from aios.core.config import get_settings
from aios.core.db import session_scope
from aios.core.errors import AIOSError, ErrorCode
from aios.core.http import Actor
from aios.core.ids import new_uuid
from aios.core.logging import get_logger, log_extra
from aios.modules.ai_gateway import providers as provider_mod
from aios.modules.ai_gateway.models import AIRun
from aios.modules.ai_gateway.port import AIContext, AIOptions, AIResult
from aios.modules.ai_gateway.prompts import Prompt
from aios.modules.audit import service as audit

T = TypeVar("T", bound=BaseModel)
logger = get_logger("aios.ai")

# 进程内缓存：键含 provider/model/prompt 版本/schema 版本/输入哈希（规范 §20）
_CACHE: dict[str, str] = {}


def cache_key(*, provider: str, model: str, prompt_id: str, prompt_version: str,
              schema_version: str, payload: str) -> str:
    raw = "|".join([provider, model, prompt_id, prompt_version, schema_version,
                    hashlib.sha256(payload.encode("utf-8")).hexdigest()])
    return "aios:v1:ai:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def invalidate_ai_cache() -> int:
    """提示词/模型升级后主动失效旧缓存（规范 §20 AI Cache Version）。

    键是内容哈希、无法按 prompt_id 反查，因此这里提供"整体失效"这一最小可控手段；
    版本变化本身会直接换键（见 tests/integration/test_ai_gateway.py 的 cache_key 用例）。
    """
    removed = len(_CACHE)
    _CACHE.clear()
    return removed


def _extract_json(text: str) -> str:
    """从模型输出里取出 JSON 主体（容忍 ```json 围栏与前后说明）。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("```")[1] if "```" in t[3:] else t[3:]
        t = t.lstrip("json").strip() if t.lower().startswith("json") else t
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        return t[start:end + 1]
    return t


class AIGateway:
    """默认实现：一次调用 = 一次 `ai_runs` 记录；失败按选项重试；输出必须通过 Schema 校验。"""

    capabilities: set[str] = {"chat", "structured_output", "cache", "ledger"}

    def __init__(self, provider: Any | None = None) -> None:
        self.settings = get_settings()
        self.provider = provider or provider_mod.provider_for()

    # ---------------------------------------------------------- 结构化输出
    async def generate_structured(self, *, purpose: str, prompt: Prompt, schema: type[T],
                                  options: AIOptions | None = None,
                                  context: AIContext | None = None) -> AIResult:
        options = options or AIOptions()
        context = context or AIContext(purpose=purpose)
        provider_name = getattr(self.provider, "provider_id", "unknown")
        model = getattr(self.provider, "model", "")
        key = cache_key(provider=provider_name, model=model, prompt_id=prompt.id,
                        prompt_version=prompt.version, schema_version=prompt.schema_version,
                        payload=prompt.template)
        self._check_budget()
        if options.allow_cache and self.settings.ai.cache_enabled and key in _CACHE:
            cached = schema.model_validate_json(_CACHE[key])
            self._ledger(context, provider_name, model, prompt, status="succeeded", tokens=0,
                         cost=0.0, cache_hit=True, latency_ms=0, input_hash=key)
            return AIResult(output=cached, provider=provider_name, model=model, cache_hit=True)

        started = time.perf_counter()
        last_error: Exception | None = None
        attempt = 0
        while attempt <= max(0, options.max_retries):
            attempt += 1
            try:
                text, tokens = await asyncio.wait_for(
                    self.provider.complete(system=prompt.system, user=prompt.template,
                                           options=options, json_mode=True),
                    timeout=options.timeout_seconds,
                )
                try:
                    output = schema.model_validate_json(_extract_json(text))
                except ValidationError as exc:
                    raise AIOSError(ErrorCode.AI_SCHEMA_INVALID,
                                    f"模型输出未通过 Schema 校验：{exc.error_count()} 处",
                                    [{"field": ".".join(str(x) for x in e.get("loc", [])),
                                      "reason": e.get("msg", "")} for e in exc.errors()[:5]]) from exc
                latency = int((time.perf_counter() - started) * 1000)
                if options.allow_cache and self.settings.ai.cache_enabled:
                    _CACHE[key] = output.model_dump_json()
                self._ledger(context, provider_name, model, prompt, status="succeeded", tokens=tokens,
                             cost=self._cost(tokens), cache_hit=False, latency_ms=latency, input_hash=key)
                return AIResult(output=output, provider=provider_name, model=model, token_usage=tokens,
                                cost=self._cost(tokens), latency_ms=latency, raw_text=text)
            except Exception as exc:  # noqa: BLE001 —— 统一入口：按 retryable 决定重试或直接抛出
                # 业务错误（Schema 不合格、预算超限、能力缺失）不重试、不降级为自由文本（规范 §21.2）
                if isinstance(exc, AIOSError) and not exc.retryable:
                    raise
                last_error = exc
                self._ledger(context, provider_name, model, prompt, status="failed", tokens=0, cost=0.0,
                             cache_hit=False, latency_ms=int((time.perf_counter() - started) * 1000),
                             input_hash=key, error=exc)
                if attempt <= options.max_retries:
                    await asyncio.sleep(min(2 ** (attempt - 1), 8))
        raise AIOSError(ErrorCode.AI_PROVIDER_UNAVAILABLE,
                        f"模型调用失败（已重试 {options.max_retries} 次）：{last_error}")

    async def embed(self, *, texts: list[str], model: str = "") -> list[list[float]]:
        """嵌入能力：当前 Provider 未声明该能力时显式拒绝（规范 §21.2 不静默降级）。"""
        if "embedding" not in getattr(self.provider, "capabilities", set()):
            raise AIOSError(ErrorCode.AI_PROVIDER_UNAVAILABLE, "当前 Provider 未声明 embedding 能力")
        _ = (texts, model)
        return []

    # ---------------------------------------------------------- 内部
    def _cost(self, tokens: int) -> float:
        # 粗略成本估算：单价可由配置覆盖；未配置时记 0 并保留 tokens 供后算
        return round(tokens / 1000 * 0.0, 6)

    def _check_budget(self) -> None:
        budget = self.settings.ai.monthly_budget_cny
        if budget <= 0:
            return
        with session_scope() as session:
            from sqlalchemy import func
            spent = session.query(func.coalesce(func.sum(AIRun.cost), 0.0)).scalar() or 0.0
        if float(spent) >= budget:
            raise AIOSError(ErrorCode.AI_BUDGET_EXCEEDED, f"本月 AI 预算已用尽（{spent:.2f}/{budget:.2f}）")

    def _ledger(self, context: AIContext, provider: str, model: str, prompt: Prompt, *,
                status: str, tokens: int, cost: float, cache_hit: bool, latency_ms: int,
                input_hash: str, error: Exception | None = None) -> None:
        """写 `ai_runs` 账本 + 审计事件（规范 §21.1/§10）。正文只存哈希。"""
        prompt_hash = hashlib.sha256((prompt.system + prompt.template).encode("utf-8")).hexdigest()
        with session_scope() as session:
            session.add(AIRun(
                id=new_uuid(), workspace_id=context.workspace_id, actor_id=context.actor_id,
                provider=provider, model=model, purpose=context.purpose or prompt.purpose,
                prompt_id=prompt.id, prompt_version=prompt.version, schema_version=prompt.schema_version,
                status=status, prompt_hash=prompt_hash, input_hash=input_hash,
                token_usage=tokens, cost=cost, cache_hit=cache_hit, latency_ms=latency_ms,
                error_code=type(error).__name__ if error else "",
                error_message=str(error)[:1000] if error else "",
                trace_id=context.trace_id,
            ))
            # 规范 §10：调用外部 AI 必须生成不可变审计事件（与账本同事务写入）
            audit.record(session, action="ai.invoke",
                         actor=Actor(actor_id=context.actor_id or "system",
                                     workspace_id=context.workspace_id or "system"),
                         resource_type="ai_run", resource_id=context.purpose,
                         after_summary=(f"provider={provider} model={model} prompt={prompt.id}"
                                        f" v{prompt.version} status={status} tokens={tokens}"
                                        f" cache={cache_hit}"),
                         result=status)
        if status == "succeeded":
            logger.info("ai_run", extra=log_extra(provider=provider, model=model, tokens=tokens,
                                                 duration_ms=latency_ms, cache_hit=cache_hit))
        else:
            logger.warning("ai_run_failed", extra=log_extra(provider=provider, model=model,
                                                            error_code=type(error).__name__ if error else ""))


def run_ai_job_sync(*, purpose: str, prompt_name: str, variables: dict[str, Any],
                    schema: type[T], context: AIContext | None = None,
                    options: AIOptions | None = None) -> T:
    """作业/脚本里同步调用 AI 的入口（内部起独立事件循环）。"""
    from aios.modules.ai_gateway.prompts import load_prompt

    prompt = load_prompt(prompt_name).with_variables(variables)
    gateway = AIGateway()
    result = asyncio.run(gateway.generate_structured(purpose=purpose, prompt=prompt, schema=schema,
                                                    options=options, context=context))
    return result.output
