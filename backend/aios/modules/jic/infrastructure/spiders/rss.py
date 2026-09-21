"""RSS / Atom Spider（规范 §14.2）：只解析用户明确授权的公开订阅源。"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from aios.contracts import DiscoveredItem, DiscoveryPage, FetchedPage, ParsedJobPosting
from aios.modules.jic.domain.normalize import canonicalize_url, detect_employment_type, detect_seniority, host_of
from aios.modules.jic.infrastructure.spiders.base import Spider, strip_html

_ATOM = "{http://www.w3.org/2005/Atom}"


class RssSpider(Spider):
    source_type = "rss"

    def discover(self, cursor: str | None = None) -> DiscoveryPage:
        urls = [u for u in (self.settings.get("feed_urls") or []) if u]
        if self.base_url and self.base_url not in urls:
            urls.insert(0, self.base_url)
        return DiscoveryPage(items=[DiscoveredItem(url=u) for u in urls], exhausted=True)

    def parse(self, page: FetchedPage) -> ParsedJobPosting:
        """RSS 的 fetch 结果直接是 feed 文本，这里取第一条 entry 作为代表条目。

        真实运行时应用层会按 entry 逐条落库；本切片先落一条以跑通链路（见 docs 说明）。
        """
        try:
            root = ET.fromstring(page.content or "<empty/>")
        except ET.ParseError:
            return ParsedJobPosting(source_key=self.source_type, canonical_url=canonicalize_url(page.url),
                                    confidence=0.1, raw_ref=host_of(page.url))
        item = root.find(".//item") or root.find(f".//{_ATOM}entry")
        if item is None:
            return ParsedJobPosting(source_key=self.source_type, canonical_url=canonicalize_url(page.url),
                                    confidence=0.1, raw_ref=host_of(page.url))
        title = (item.findtext("title") or item.findtext(f"{_ATOM}title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not link:
            link_el = item.find(f"{_ATOM}link")
            link = (link_el.get("href") if link_el is not None else "") or ""
        summary = strip_html(item.findtext("description") or item.findtext(f"{_ATOM}summary") or "")
        published = None
        raw_date = item.findtext("pubDate") or item.findtext(f"{_ATOM}updated") or ""
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                published = datetime.strptime(raw_date.strip(), fmt)
                break
            except ValueError:
                continue
        confidence = 0.5 + (0.2 if title else 0.0) + (0.2 if link else 0.0)
        return ParsedJobPosting(
            source_key=self.settings.get("source_key", self.source_type),
            external_id=link or title,
            canonical_url=canonicalize_url(link or page.url),
            company_name=self.settings.get("company_name", ""),
            title=title,
            description=summary[:4000],
            employment_type=detect_employment_type(summary),
            seniority=detect_seniority(title),
            published_at=published,
            raw_ref=host_of(page.url),
            confidence=round(min(1.0, confidence), 2),
        )
