"""自定义 Spider（规范 §14.2）：用配置里的正则/JSON-LD 路径适配长尾站点，不写死任何站点。

配置示例（job_sources.policy 之外放在 source.settings 里）：
```json
{
  "urls": ["https://example.com/job/1"],
  "fields": {
    "title": "<h1[^>]*>(.*?)</h1>",
    "company": "公司[：:]\\s*([^<\\n]{2,30})",
    "location": "地点[：:]\\s*([^<\\n]{2,20})",
    "salary": "(\\d+[kK万]\\s*[-~—]\\s*\\d+[kK万])"
  }
}
```
"""
from __future__ import annotations

import re

from aios.contracts import DiscoveredItem, DiscoveryPage, FetchedPage, ParsedJobPosting
from aios.modules.jic.domain.normalize import canonicalize_url, detect_employment_type, detect_seniority, host_of
from aios.modules.jic.infrastructure.spiders.base import Spider, strip_html


class CustomSpider(Spider):
    source_type = "custom"

    def discover(self, cursor: str | None = None) -> DiscoveryPage:
        urls = [u for u in (self.settings.get("urls") or []) if u]
        if self.base_url and self.base_url not in urls:
            urls.insert(0, self.base_url)
        return DiscoveryPage(items=[DiscoveredItem(url=u) for u in urls], exhausted=True)

    def parse(self, page: FetchedPage) -> ParsedJobPosting:
        html = page.content or ""
        text = strip_html(html)
        fields: dict[str, str] = self.settings.get("fields") or {}

        def field(name: str) -> str:
            pattern = fields.get(name)
            if not pattern:
                return ""
            m = re.search(pattern, html if "<" in pattern else text, re.S | re.I)
            return (m.group(1) if m and m.groups() else (m.group(0) if m else "")).strip()

        title = field("title") or ""
        company = field("company")
        description = field("description") or text[:4000]
        confidence = 0.35 + (0.25 if title else 0) + (0.2 if company else 0) + (0.2 if len(description) >= 120 else 0)
        return ParsedJobPosting(
            source_key=self.settings.get("source_key", self.source_type),
            external_id=field("external_id"),
            canonical_url=canonicalize_url(page.url),
            company_name=company,
            title=title,
            location=field("location"),
            work_mode=field("work_mode"),
            employment_type=field("employment_type") or detect_employment_type(description),
            seniority=field("seniority") or detect_seniority(title),
            description=description[:8000],
            salary_text=field("salary"),
            raw_ref=host_of(page.url),
            confidence=round(min(1.0, confidence), 2),
        )
