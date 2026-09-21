"""SpiderManager（规范 §14.2）：所有 Spider 必须注册到这里，由 Application 层统一调度。"""
from __future__ import annotations

from typing import Any

from aios.contracts import JobSourcePolicy, SpiderHealth
from aios.modules.jic.infrastructure.spiders.base import Spider


class SpiderManager:
    """插件注册表。Application 层只通过本类拿到 Spider，不直接 import 具体实现。"""

    def __init__(self) -> None:
        self._registry: dict[str, type[Spider]] = {}

    def register(self, spider_cls: type[Spider]) -> type[Spider]:
        self._registry[spider_cls.source_type] = spider_cls
        return spider_cls

    def registered_types(self) -> list[str]:
        return sorted(self._registry)

    def create(self, *, source_type: str, base_url: str, settings: dict[str, Any] | None = None,
               policy: JobSourcePolicy | None = None) -> Spider:
        spider_cls = self._registry.get(source_type)
        if spider_cls is None:
            raise KeyError(f"未注册的来源类型：{source_type}（已注册：{', '.join(self.registered_types())}）")
        allowed = [policy.domain] if policy and policy.domain else []
        merged = {**(settings or {})}
        if policy is not None:
            merged.setdefault("max_page_depth", policy.max_page_depth)
        return spider_cls(base_url=base_url, settings=merged, allowed_domains=allowed)

    def health(self, *, source_type: str, base_url: str,
               policy: JobSourcePolicy | None = None) -> SpiderHealth:
        try:
            spider = self.create(source_type=source_type, base_url=base_url, policy=policy)
        except KeyError as exc:
            return SpiderHealth(source_key=source_type, ok=False, detail=str(exc))
        return spider.health_check()


manager = SpiderManager()
