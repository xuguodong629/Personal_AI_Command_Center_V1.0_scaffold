"""公共 HTML 岗位页 Spider（规范 §14.2）：优先解析 schema.org JobPosting JSON-LD。"""
from __future__ import annotations

import json
import re

from aios.contracts import DiscoveredItem, DiscoveryPage, FetchedPage, ParsedJobPosting
from aios.modules.jic.domain.normalize import (
    canonicalize_url,
    detect_employment_type,
    detect_seniority,
    detect_work_mode,
    host_of,
)
from aios.modules.jic.infrastructure.spiders.base import Spider, first_match, strip_html


def extract_json_ld(html: str) -> list[dict]:
    """抽取页面里的 JSON-LD 结构化数据。"""
    out: list[dict] = []
    for m in re.finditer(r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html or ""):
        raw = (m.group(1) or "").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "@graph" in data:
            out.extend([x for x in data.get("@graph") or [] if isinstance(x, dict)])
        elif isinstance(data, dict):
            out.append(data)
        elif isinstance(data, list):
            out.extend([x for x in data if isinstance(x, dict)])
    return out


def find_job_posting(blocks: list[dict]) -> dict:
    for block in blocks:
        types = block.get("@type") or ""
        types = types if isinstance(types, list) else [types]
        if any(str(t).lower() == "jobposting" for t in types):
            return block
    return {}


def _location_from_json_ld(block: dict) -> str:
    loc = block.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    if not isinstance(loc, dict):
        return ""
    addr = loc.get("address") or {}
    if isinstance(addr, dict):
        return " ".join(str(addr.get(k, "")) for k in ("addressLocality", "addressRegion") if addr.get(k)).strip()
    return str(addr)


class PublicHtmlSpider(Spider):
    """通用公开岗位页：用户导入的链接或受审来源的岗位详情页。"""

    source_type = "public_html"

    def discover(self, cursor: str | None = None) -> DiscoveryPage:
        urls = [u for u in (self.settings.get("urls") or []) if u]
        if self.base_url and self.base_url not in urls:
            urls.insert(0, self.base_url)
        items = [DiscoveredItem(url=u, depth=0) for u in urls]
        return DiscoveryPage(items=items, cursor=None, exhausted=True)

    def parse(self, page: FetchedPage) -> ParsedJobPosting:
        html = page.content or ""
        text = strip_html(html)
        blocks = extract_json_ld(html)
        job = find_job_posting(blocks)

        title = str(job.get("title") or "") or first_match(
            (r"<h1[^>]*>(.*?)</h1>", r"<title[^>]*>(.*?)</title>"), html)
        company = ""
        org = job.get("hiringOrganization") or {}
        if isinstance(org, dict):
            company = str(org.get("name") or "")
        if not company:
            company = first_match((r"招聘[_\s]*([\u4e00-\u9fffA-Za-z0-9（）()]{2,30}?(?:公司|集团|电器|商贸|科技))",
                                   r"([\u4e00-\u9fff]{2,22}(?:有限公司|股份有限公司|集团))"), text)
        description = str(job.get("description") or "")
        description = strip_html(description) if description else text[:4000]
        location = _location_from_json_ld(job) or first_match(
            (r"工作地点[：:\s]*([\u4e00-\u9fff]{2,20})", r"地点[：:\s]*([\u4e00-\u9fff]{2,20})"), text)
        salary_text = ""
        salary = job.get("baseSalary")
        if isinstance(salary, dict):
            val = salary.get("value") or {}
            if isinstance(val, dict):
                salary_text = f"{val.get('minValue', '')}-{val.get('maxValue', '')} {salary.get('currency', '')}".strip()
        published = None
        if job.get("datePosted"):
            from datetime import datetime
            try:
                published = datetime.fromisoformat(str(job["datePosted"]).replace("Z", "+00:00"))
            except ValueError:
                published = None

        blob = f"{title} {description}"
        confidence = 0.3
        if title:
            confidence += 0.2
        if company:
            confidence += 0.2
        if location:
            confidence += 0.1
        if len(description) >= 200:
            confidence += 0.2
        if job:
            confidence = min(0.95, confidence + 0.15)

        return ParsedJobPosting(
            source_key=self.settings.get("source_key", self.source_type),
            external_id=str(job.get("identifier", {}).get("value", "") if isinstance(job.get("identifier"), dict) else ""),
            canonical_url=canonicalize_url(page.url),
            company_name=company,
            title=title,
            location=location,
            work_mode=detect_work_mode(blob),
            employment_type=detect_employment_type(blob),
            seniority=detect_seniority(title),
            description=description[:8000],
            salary_text=salary_text,
            published_at=published,
            raw_ref=host_of(page.url),
            confidence=round(min(1.0, confidence), 2),
        )
