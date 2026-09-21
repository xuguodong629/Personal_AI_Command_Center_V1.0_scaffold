"""字段规范化（规范 §16.1-Normalize）：公司、地点、URL、薪资、文本哈希与指纹。

全部为纯函数，可单测（规范 §25.1：单元测试无网络、无数据库）。
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# 已知无意义/跟踪参数（规范 §15：canonical_url 去掉 UTM、会话参数与已知无意义参数）
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "spm", "from", "share_token", "share_source", "ref", "referer", "pgref", "s", "t",
    "sessionid", "jsessionid", "sid", "trackid", "clicktime",
}

COMPANY_SUFFIXES = (
    "有限责任公司", "股份有限公司", "有限公司", "集团有限公司", "集团", "公司", "分公司", "厂",
)
CITY_SUFFIXES = ("市辖区", "地区", "自治州", "省", "市", "区", "县", "旗")
WORK_MODE_KEYWORDS = {
    "remote": ("远程", "在家", "居家办公", "remote", "work from home"),
    "hybrid": ("混合办公", "弹性办公", "hybrid"),
    "onsite": ("现场办公", "坐班", "驻场", "onsite"),
}
EMPLOYMENT_KEYWORDS = {
    "full_time": ("全职", "正式", "full-time", "full time"),
    "part_time": ("兼职", "part-time"),
    "internship": ("实习", "intern", "internship"),
    "contract": ("外包", "派遣", "合同制", "contract"),
}
SENIORITY_KEYWORDS = (
    ("director", ("总监", "总经理", "VP", "副总裁")),
    ("manager", ("经理", "主管", "负责人", "店长", "督导")),
    ("senior", ("高级", "资深", "高级经理", "专家")),
    ("junior", ("助理", "专员", "实习生", "应届")),
)

_SALARY_K = re.compile(r"(\d+(?:\.\d+)?)\s*[-~—至]\s*(\d+(?:\.\d+)?)\s*[kK]")
_SALARY_WAN = re.compile(r"(\d+(?:\.\d+)?)\s*[-~—至]\s*(\d+(?:\.\d+)?)\s*万")
_SALARY_ONE = re.compile(r"(\d+(?:\.\d+)?)\s*[kK]")


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def canonicalize_url(url: str) -> str:
    """去跟踪参数、去 fragment、统一小写主机与去尾斜杠（保留路径与业务参数）。"""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return url.strip()
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if k.lower() not in TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def normalize_company(name: str) -> str:
    """公司名规范化：去空白与括号段、去公司类别后缀，用于实体归并与指纹。"""
    s = re.sub(r"\s+", "", name or "")
    s = re.sub(r"[（(][^）)]*[）)]", "", s)          # 「美的集团（中国）有限公司」→「美的集团有限公司」
    for suffix in COMPANY_SUFFIXES:
        if s.endswith(suffix) and len(s) > len(suffix) + 1:
            s = s[: -len(suffix)]
            break
    return s.strip()


def normalize_location(text: str) -> str:
    """地点规范化：去「·/、」与后缀，保留最具体的城市名。"""
    s = re.sub(r"[\s·,，/、]+", "", text or "")
    s = re.sub(r"[（(].*?[）)]", "", s)
    for suffix in CITY_SUFFIXES:
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)]
            break
    return s.strip()


def detect_work_mode(text: str) -> str:
    low = (text or "").lower()
    for mode, keys in WORK_MODE_KEYWORDS.items():
        if any(k in low for k in keys):
            return mode
    return ""


def detect_employment_type(text: str) -> str:
    low = (text or "").lower()
    for kind, keys in EMPLOYMENT_KEYWORDS.items():
        if any(k in low for k in keys):
            return kind
    return ""


def detect_seniority(title: str) -> str:
    for level, keys in SENIORITY_KEYWORDS:
        if any(k in (title or "") for k in keys):
            return level
    return ""


def parse_salary_text(text: str) -> tuple[int, int]:
    """薪资文本 → 月薪区间（元）。(0,0) 表示无法解析。规范 §11.5：金额不入浮点存储。"""
    s = text or ""
    m = _SALARY_K.search(s)
    if m:
        return int(float(m.group(1)) * 1000), int(float(m.group(2)) * 1000)
    m = _SALARY_WAN.search(s)
    if m:
        lo, hi = float(m.group(1)) * 10000, float(m.group(2)) * 10000
        if "年" in s:
            return int(lo / 12), int(hi / 12)
        return int(lo), int(hi)
    m = _SALARY_ONE.search(s)
    if m:
        v = int(float(m.group(1)) * 1000)
        return v, v
    return 0, 0


def fingerprint(*, company: str, title: str, location: str, domain: str, description: str) -> str:
    """职位指纹（规范 §15）：公司名 + 职位名 + 地点 + 来源域名 + 正文前 N 个有效词。

    仅标题相同不得直接合并；指纹相同视为同一职位候选。
    """
    desc_head = "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", description or "")[:30])
    payload = "|".join([
        normalize_company(company).lower(),
        re.sub(r"\s+", "", (title or "").lower()),
        normalize_location(location).lower(),
        (domain or "").lower(),
        desc_head.lower(),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def host_of(url: str) -> str:
    return (urlsplit(url or "").netloc or "").lower().split(":")[0]
