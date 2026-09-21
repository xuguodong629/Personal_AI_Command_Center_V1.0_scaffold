"""规范化与指纹单元测试（规范 §25.1：无网络、无数据库）。"""
from __future__ import annotations

import pytest
from aios.modules.jic.domain.normalize import (
    canonicalize_url,
    detect_employment_type,
    detect_seniority,
    detect_work_mode,
    fingerprint,
    normalize_company,
    normalize_location,
    parse_salary_text,
)

pytestmark = pytest.mark.unit


def test_given_url_with_tracking_when_canonicalized_then_params_removed():
    url = "HTTPS://Jobs.51job.com/Zhengzhou/172984462.html?utm_source=x&pgRef=abc&s=gsxq#frag"
    assert canonicalize_url(url) == "https://jobs.51job.com/Zhengzhou/172984462.html"


def test_given_url_without_scheme_when_canonicalized_then_unchanged():
    assert canonicalize_url("郑州 区域经理") == "郑州 区域经理"


def test_given_company_with_suffix_when_normalized_then_suffix_removed():
    assert normalize_company("郑州环尔先网络科技有限公司") == "郑州环尔先网络科技"
    assert normalize_company(" 美的集团（中国）有限公司 ") == "美的集团"


def test_given_location_with_suffix_when_normalized_then_city_kept():
    assert normalize_location("河南省郑州市") == "河南省郑州"
    # 去掉一个行政区后缀后仍必须保留城市名（匹配靠包含关系，不靠全等）
    assert "郑州" in normalize_location("郑州·金水区")


@pytest.mark.parametrize("text,expected", [
    ("15-20K·13薪", (15000, 20000)),
    ("年薪15-30万", (12500, 25000)),
    ("8千-1.2万", (0, 0)),          # 中文「千/万」混写不在本切片解析范围（保守返回 0）
    ("面议", (0, 0)),
])
def test_given_salary_text_when_parsed_then_range(text, expected):
    assert parse_salary_text(text) == expected


def test_given_title_when_detected_then_seniority_and_type():
    assert detect_seniority("区域销售经理") == "manager"
    assert detect_seniority("渠道总监") == "director"
    assert detect_employment_type("实习生招聘") == "internship"
    assert detect_work_mode("可远程办公") == "remote"


def test_given_same_job_when_fingerprinted_then_stable_and_sensitive_to_changes():
    base = dict(company="美的集团", title="区域销售经理", location="郑州", domain="jobs.51job.com",
                description="负责河南区域渠道开发与经销商维护")
    assert fingerprint(**base) == fingerprint(**base)
    changed = {**base, "location": "洛阳"}
    assert fingerprint(**base) != fingerprint(**changed)


def test_given_only_title_same_when_other_fields_differ_then_fingerprint_differs():
    """规范 §15：不将仅标题相同的记录直接合并。"""
    a = dict(company="A公司", title="区域经理", location="郑州", domain="x.com", description="渠道")
    b = dict(company="B公司", title="区域经理", location="郑州", domain="x.com", description="渠道")
    assert fingerprint(**a) != fingerprint(**b)
