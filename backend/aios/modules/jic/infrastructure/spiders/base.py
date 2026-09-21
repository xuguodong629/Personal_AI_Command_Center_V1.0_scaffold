"""Spider 基类（规范 §6.2.7 / §14.2）：属于 Infrastructure 层。

铁律：不写数据库、不含业务规则、不调 AI、不匹配职位；只把公开页面转成标准 DTO。
"""
from __future__ import annotations

import abc
import re

import httpx

from aios.contracts import DiscoveredItem, DiscoveryPage, FetchedPage, ParsedJobPosting, SpiderHealth
from aios.core.security import validate_outbound_url

# 明确 User-Agent + 超时（规范 §16.1-Fetch）
FETCH_UA = "AIOS-JIC/1.0 (+local personal job-intelligence; contact: local-operator)"
FETCH_TIMEOUT = httpx.Timeout(15.0, connect=8.0)

# 风控/验证码特征（规范 §14.1-4：遇到立即停止该来源并记 blocked）
BLOCK_SIGNATURES = (
    "security verification", "验证码", "captcha", "人机验证", "访问过于频繁",
    "请稍候", "正在加载中", "access denied", "forbidden", "robot check",
)


def detect_block(status: int, content: str) -> str:
    """返回 blocked 原因；空字符串表示未被封禁。"""
    if status in (401, 403):
        return f"http_{status}"
    if status == 429:
        return "http_429"
    low = (content or "").lower()
    for sig in BLOCK_SIGNATURES:
        if sig in low:
            return f"signature:{sig}"
    return ""


class Spider(abc.ABC):
    """统一接口（规范 §14.2）：discover / fetch / parse / health_check。"""

    source_type: str = "public_html"

    def __init__(self, *, base_url: str = "", settings: dict | None = None,
                 allowed_domains: list[str] | None = None) -> None:
        self.base_url = base_url
        self.settings = settings or {}
        self.allowed_domains = allowed_domains or []

    # ---- 生命周期 -------------------------------------------------
    @abc.abstractmethod
    def discover(self, cursor: str | None = None) -> DiscoveryPage:
        """发现待抓取条目（不得无上限翻页，深度受策略限制）。"""

    def fetch(self, item: DiscoveredItem) -> FetchedPage:
        """抓取单个条目。默认实现：httpx + 明确 UA + 超时 + 封禁特征识别。"""
        url = validate_outbound_url(item.url, allowed_domains=self.allowed_domains, resolve_dns=False)
        headers = {"User-Agent": FETCH_UA, "Accept-Language": "zh-CN,zh;q=0.9"}
        with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True, trust_env=False,
                          headers=headers) as client:
            resp = client.get(url)
        content = resp.text or ""
        return FetchedPage(url=url, status=resp.status_code, content=content,
                           content_type=resp.headers.get("content-type", "text/html"),
                           blocked_reason=detect_block(resp.status_code, content))

    @abc.abstractmethod
    def parse(self, page: FetchedPage) -> ParsedJobPosting:
        """把页面转成 ParsedJobPosting；置信度不足时 confidence < 0.5，由应用层转人工复核。"""

    def health_check(self) -> SpiderHealth:
        """来源健康检查（不发起真实抓取，只校验配置完整性）。"""
        problems = []
        if not self.base_url:
            problems.append("base_url 为空")
        if not self.allowed_domains:
            problems.append("未配置允许域名（来源策略缺失）")
        return SpiderHealth(source_key=self.source_type, ok=not problems, detail="；".join(problems))


def strip_html(html: str) -> str:
    """轻量正文抽取：优先 trafilatura，失败退回去标签。"""
    try:
        import trafilatura

        text = trafilatura.extract(html or "", include_comments=False, include_tables=False) or ""
        if len(text.strip()) >= 80:
            return text.strip()
    except Exception:  # noqa: BLE001 —— 抽取失败退回正则，不吞掉业务错误
        pass
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def first_match(patterns: tuple[str, ...], text: str, group: int = 1) -> str:
    for pat in patterns:
        m = re.search(pat, text or "", re.S | re.I)
        if m:
            return (m.group(group) or "").strip()
    return ""
