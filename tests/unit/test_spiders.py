"""Spider 解析与封禁识别单元测试（规范 §25.2-2/3：解析器缺字段、页面变更、验证码特征）。"""
from __future__ import annotations

import pytest
from aios.contracts import FetchedPage
from aios.modules.jic.infrastructure.spiders import spider_manager
from aios.modules.jic.infrastructure.spiders.base import detect_block
from aios.modules.jic.infrastructure.spiders.public_html import PublicHtmlSpider, extract_json_ld
from aios.modules.jic.infrastructure.spiders.rss import RssSpider

pytestmark = pytest.mark.unit

JSON_LD_HTML = """
<html><head><title>【郑州 区域经理招聘】-某某电器有限公司</title>
<script type="application/ld+json">
{"@type":"JobPosting","title":"区域销售经理","datePosted":"2026-09-01",
 "hiringOrganization":{"@type":"Organization","name":"某某电器有限公司"},
 "jobLocation":{"address":{"addressLocality":"郑州","addressRegion":"河南"}},
 "description":"<p>负责河南区域渠道开发与经销商维护，完成年度销售与回款指标。</p>",
 "baseSalary":{"currency":"CNY","value":{"minValue":15000,"maxValue":20000}}}
</script></head><body><h1>区域销售经理</h1></body></html>
"""


@pytest.mark.parametrize("status,content,expected", [
    (200, "Security Verification", "signature:security verification"),
    (200, "请输入验证码继续", "signature:验证码"),
    (403, "forbidden", "http_403"),
    (429, "too many requests", "http_429"),
    (200, "正常岗位页面内容", ""),
])
def test_given_block_signals_when_detected_then_reason(status, content, expected):
    assert detect_block(status, content) == expected


def test_given_json_ld_job_posting_when_parsed_then_all_fields_extracted():
    spider = PublicHtmlSpider(base_url="https://jobs.example.com/job/1",
                              settings={"source_key": "demo"}, allowed_domains=["jobs.example.com"])
    parsed = spider.parse(FetchedPage(url="https://jobs.example.com/job/1?utm_source=x",
                                      status=200, content=JSON_LD_HTML))
    assert parsed.title == "区域销售经理"
    assert parsed.company_name == "某某电器有限公司"
    assert parsed.location == "郑州 河南"
    assert parsed.salary_text.startswith("15000-20000")
    assert parsed.employment_type == "" and parsed.seniority == "manager"
    assert parsed.confidence >= 0.9
    assert "utm_source" not in parsed.canonical_url


def test_given_plain_html_without_json_ld_when_parsed_then_low_confidence():
    spider = PublicHtmlSpider(base_url="https://jobs.example.com/job/2", allowed_domains=["jobs.example.com"])
    parsed = spider.parse(FetchedPage(url="https://jobs.example.com/job/2", status=200,
                                      content="<html><body><h1>销售</h1></body></html>"))
    assert parsed.confidence < 0.75
    assert parsed.title in ("销售", "jobs.example.com")


def test_given_empty_page_when_parsed_then_no_crash():
    spider = PublicHtmlSpider(base_url="https://jobs.example.com/job/3")
    parsed = spider.parse(FetchedPage(url="https://jobs.example.com/job/3", status=200, content=""))
    assert parsed.title == ""
    assert parsed.confidence <= 0.5


def test_given_rss_feed_when_parsed_then_first_item_fields():
    feed = """<?xml version="1.0"?><rss><channel>
    <item><title>渠道经理</title><link>https://careers.example.com/job/9?utm_campaign=x</link>
    <description><![CDATA[<p>负责渠道开发与回款</p>]]></description>
    <pubDate>Mon, 01 Sep 2026 08:00:00 +0800</pubDate></item></channel></rss>"""
    spider = RssSpider(base_url="https://careers.example.com/feed.xml", settings={"company_name": "示例公司"})
    parsed = spider.parse(FetchedPage(url="https://careers.example.com/feed.xml", content=feed))
    assert parsed.title == "渠道经理"
    assert parsed.company_name == "示例公司"
    assert parsed.canonical_url == "https://careers.example.com/job/9"
    assert parsed.published_at is not None


def test_given_parse_error_page_when_parsed_then_low_confidence_not_exception():
    spider = RssSpider(base_url="https://careers.example.com/feed.xml")
    parsed = spider.parse(FetchedPage(url="https://careers.example.com/feed.xml", content="<not-xml"))
    assert parsed.confidence <= 0.2


def test_given_malformed_json_ld_when_extracting_then_ignored():
    html = '<script type="application/ld+json">{not json}</script>'
    assert extract_json_ld(html) == []


def test_given_builtin_spiders_when_queried_then_registered():
    assert set(spider_manager.registered_types()) >= {"public_html", "official_career", "rss", "custom"}
