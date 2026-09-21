"""Provider 适配器（规范 §6.2.6 / §21.2）：OpenAI 兼容实现 + 本地 Fake 实现。

密钥只在本层读取（规范 §8：所有密钥只可被基础设施适配器读取）；业务层只拿到 AIService。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from aios.core.config import PROJECT_ROOT
from aios.core.errors import AIOSError, ErrorCode
from aios.modules.ai_gateway.port import AIOptions

AI_CONFIG_FILE = PROJECT_ROOT / "data" / "config" / "ai.json"


def load_provider_configs() -> list[dict[str, Any]]:
    """读取既有 data/config/ai.json（与 app/ai.py 同一份配置，避免重复维护）。"""
    if not AI_CONFIG_FILE.exists():
        return []
    try:
        data = json.loads(AI_CONFIG_FILE.read_text("utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return []
    providers = data.get("providers") if isinstance(data, dict) else data
    return [p for p in (providers or []) if isinstance(p, dict)]


class ProviderError(AIOSError):
    """Provider 传输层错误（超时/限流/5xx）：标记为可重试。"""

    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.AI_PROVIDER_UNAVAILABLE, message, retryable=True)


class OpenAICompatibleProvider:
    """OpenAI 兼容 chat/completions（DeepSeek、OpenAI、本地 vLLM/Ollama 皆可）。"""

    capabilities: set[str] = {"chat", "structured_output", "streaming"}

    def __init__(self, *, provider_id: str, base_url: str, api_key: str, model: str) -> None:
        self.provider_id = provider_id
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> OpenAICompatibleProvider:
        return cls(provider_id=str(cfg.get("id") or cfg.get("name") or "default"),
                   base_url=str(cfg.get("base_url") or ""),
                   api_key=str(cfg.get("api_key") or ""),
                   model=str(cfg.get("model") or ""))

    async def complete(self, *, system: str, user: str, options: AIOptions,
                       json_mode: bool = False) -> tuple[str, int]:
        """返回 (文本, 估算 token 数)。"""
        if not self.base_url or not self.model:
            raise ProviderError("Provider 配置不完整（base_url/model）")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": options.temperature,
            "max_tokens": options.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=options.timeout_seconds) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
        if resp.status_code >= 400:
            raise ProviderError(f"{self.provider_id} HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        usage = int((data.get("usage") or {}).get("total_tokens") or 0)
        if not usage:
            usage = max(1, (len(system) + len(user) + len(text)) // 4)
        return text, usage


class FakeProvider:
    """测试用 Provider（规范 §30.4）：不联网、可编排失败与非法输出。"""

    capabilities: set[str] = {"chat", "structured_output"}

    def __init__(self, *, response: str = "{}", fail_times: int = 0, model: str = "fake-model") -> None:
        self.response = response
        self.fail_times = fail_times
        self.model = model
        self.provider_id = "fake"
        self.calls = 0

    async def complete(self, *, system: str, user: str, options: AIOptions,
                       json_mode: bool = False) -> tuple[str, int]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError("fake provider transient failure")
        return self.response, 42


def provider_for(provider_id: str = "") -> Any:
    """按 id 取 Provider；未指定时取第一个可用配置；都没有则返回 Fake（只用于离线开发）。"""
    configs = load_provider_configs()
    if provider_id:
        for cfg in configs:
            if str(cfg.get("id")) == provider_id:
                return OpenAICompatibleProvider.from_config(cfg)
    if configs:
        return OpenAICompatibleProvider.from_config(configs[0])
    return FakeProvider(response="{}")


def now_ms() -> int:
    return int(time.time() * 1000)


def config_path() -> Path:
    return AI_CONFIG_FILE
