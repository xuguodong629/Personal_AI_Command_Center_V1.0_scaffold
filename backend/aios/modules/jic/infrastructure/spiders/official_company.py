"""官方社招页 Spider（规范 §14.2）：只在来源策略允许时抓取企业自有招聘域名。"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from aios.contracts import DiscoveredItem, DiscoveryPage, ParsedJobPosting
from aios.core.security import validate_outbound_url
from aios.modules.jic.domain.normalize import canonicalize_url, host_of
from aios.modules.jic.infrastructure.spiders.public_html import PublicHtmlSpider


class OfficialCompanySpider(PublicHtmlSpider):
    """企业官网/官方招聘站：从索引页发现岗位详情链接，再按公共解析器解析。"""

    source_type = "official_career"

    def discover(self, cursor: str | None = None) -> DiscoveryPage:
        index_urls = list(self.settings.get("index_urls") or [])
        detail_urls = list(self.settings.get("urls") or [])
        max_depth = int(self.settings.get("max_page_depth") or 1)
        link_pattern = self.settings.get("link_pattern") or r"(job|position|zhaopin|recruit|social|detail)"

        items: list[DiscoveredItem] = [DiscoveredItem(url=u, depth=0) for u in detail_urls]
        for index_url in index_urls[: max(1, max_depth)]:
            page = self.fetch(DiscoveredItem(url=index_url))
            if page.blocked_reason or page.status >= 400:
                continue
            base = canonicalize_url(index_url)
            found: list[str] = []
            for href in re.findall(r'(?is)href=["\']([^"\']+)["\']', page.content or ""):
                if not re.search(link_pattern, href, re.I):
                    continue
                absolute = urljoin(base, href)
                host = host_of(absolute)
                if self.allowed_domains and not any(host == d or host.endswith("." + d) for d in self.allowed_domains):
                    continue
                try:
                    validate_outbound_url(absolute, allowed_domains=self.allowed_domains, resolve_dns=False)
                except Exception:  # noqa: BLE001 —— 单个链接不合法只跳过
                    continue
                if absolute not in found:
                    found.append(absolute)
            for url in found[: int(self.settings.get("max_items") or 20)]:
                items.append(DiscoveredItem(url=url, depth=1))
        return DiscoveryPage(items=items, cursor=None, exhausted=True)

    def parse(self, page) -> ParsedJobPosting:  # type: ignore[override]
        parsed = super().parse(page)
        parsed.source_key = self.settings.get("source_key", self.source_type)
        parsed.extra = {**(parsed.extra or {}), "official": True}
        if parsed.confidence < 0.75:
            parsed.confidence = round(parsed.confidence, 2)
        return parsed
