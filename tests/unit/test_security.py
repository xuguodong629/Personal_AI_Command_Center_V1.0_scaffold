"""SSRF / 出网校验单元测试（规范 §23.1/§23.2/§25.2-5）。"""
from __future__ import annotations

import pytest
from aios.core.errors import AIOSError
from aios.core.security import validate_outbound_url

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("url", [
    "file:///C:/Windows/win.ini",
    "data:text/html;base64,PHNjcmlwdD4=",
    "ftp://example.com/a",
    "javascript:alert(1)",
])
def test_given_forbidden_scheme_when_validated_then_rejected(url):
    with pytest.raises(AIOSError) as err:
        validate_outbound_url(url, resolve_dns=False)
    assert err.value.code.value == "VALIDATION_ERROR"


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://100.100.100.200/latest/meta-data/",
])
def test_given_metadata_endpoint_when_validated_then_forbidden(url):
    with pytest.raises(AIOSError) as err:
        validate_outbound_url(url, resolve_dns=False)
    assert err.value.code.value in ("FORBIDDEN", "VALIDATION_ERROR")


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8787/api/health",
    "http://localhost/admin",
    "http://192.168.1.10/router",
    "http://[::1]/",
])
def test_given_private_or_loopback_when_dns_resolved_then_forbidden(url):
    with pytest.raises(AIOSError) as err:
        validate_outbound_url(url, resolve_dns=True)
    assert err.value.code.value == "FORBIDDEN"


def test_given_domain_not_in_allowlist_when_validated_then_source_not_allowed():
    with pytest.raises(AIOSError) as err:
        validate_outbound_url("https://evil.example/job/1", allowed_domains=["jobs.51job.com"],
                              resolve_dns=False)
    assert err.value.code.value == "JOB_SOURCE_NOT_ALLOWED"


def test_given_public_url_in_allowlist_when_validated_then_ok():
    url = "https://jobs.51job.com/zhengzhou/172984462.html"
    assert validate_outbound_url(url, allowed_domains=["51job.com"], resolve_dns=False) == url
