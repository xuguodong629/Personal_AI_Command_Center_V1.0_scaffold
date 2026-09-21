"""安全工具（规范 §23）：URL 导入与抓取的 SSRF 防护 + 域名允许列表。

拒绝：非 http(s) 协议、`file:`/`data:`、私网/回环/链路本地地址、云元数据地址、未在来源策略中的域名。
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from aios.core.errors import AIOSError, ErrorCode

METADATA_HOSTS = {
    "169.254.169.254",            # AWS/GCP/Azure/阿里云 元数据
    "metadata.google.internal",
    "100.100.100.200",            # 阿里云元数据
}

BLOCKED_SCHEMES = {"file", "data", "ftp", "gopher", "javascript", "blob"}


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified)


def validate_outbound_url(url: str, *, allowed_domains: list[str] | None = None,
                          resolve_dns: bool = True) -> str:
    """校验一个将要出网抓取的 URL；不合法直接抛 AIOSError（规范 §23.1/§23.2）。

    `allowed_domains` 为空表示不限制域名（如用户手工导入自己的链接）；非空时必须命中。
    """
    raw = (url or "").strip()
    if not raw:
        raise AIOSError(ErrorCode.VALIDATION_ERROR, "URL 为空", [{"field": "url", "reason": "empty"}])
    parts = urlsplit(raw)
    scheme = (parts.scheme or "").lower()
    if scheme in BLOCKED_SCHEMES or scheme not in ("http", "https"):
        raise AIOSError(ErrorCode.VALIDATION_ERROR, f"不允许的协议：{parts.scheme or '空'}",
                        [{"field": "url", "reason": "scheme_not_allowed"}])
    host = (parts.hostname or "").lower()
    if not host:
        raise AIOSError(ErrorCode.VALIDATION_ERROR, "URL 缺少主机名",
                        [{"field": "url", "reason": "missing_host"}])
    if host in METADATA_HOSTS:
        raise AIOSError(ErrorCode.FORBIDDEN, "拒绝访问云元数据地址",
                        [{"field": "url", "reason": "metadata_endpoint"}])
    if allowed_domains and not any(host == d.lower() or host.endswith("." + d.lower()) for d in allowed_domains):
        raise AIOSError(ErrorCode.JOB_SOURCE_NOT_ALLOWED, "该域名不在来源允许列表中",
                        [{"field": "url", "reason": "domain_not_allowed"}])
    if resolve_dns:
        try:
            infos = socket.getaddrinfo(host, parts.port or (443 if scheme == "https" else 80),
                                       proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise AIOSError(ErrorCode.VALIDATION_ERROR, f"域名无法解析：{host}",
                            [{"field": "url", "reason": "dns_failure"}]) from exc
        for info in infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if _is_blocked_ip(ip):
                raise AIOSError(ErrorCode.FORBIDDEN, "拒绝访问内网/回环地址",
                                [{"field": "url", "reason": "private_address", "details": addr}])
    return raw
