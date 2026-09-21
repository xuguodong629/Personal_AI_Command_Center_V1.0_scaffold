"""分层定位抓取失败点：robots 是否禁止 / HTTP 状态 / 原文长度 / trafilatura 抽取长度。

用法（backend 目录）：.\.venv\Scripts\python.exe _tmp_probe_fetch2.py
"""
import asyncio
import io
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.ai import FETCH_UA, _fetch_once, _host_of, _load_search, _robots_ok  # noqa: E402

URLS = [
    ("猎聘 m·岗位详情", "https://m.liepin.com/job/1957082659.shtml"),
    ("猎聘 www·岗位详情", "https://www.liepin.com/job/1985530451.shtml"),
    ("智联 m·岗位详情", "https://m.zhaopin.com/jobs/CC302724180J40982752004.htm"),
    ("智联 jobs·岗位详情", "https://jobs.zhaopin.com/CCL1351485350J40888539713.htm"),
    ("智联 www·岗位详情", "https://www.zhaopin.com/jobdetail/CC594058120J40489901910.htm"),
    ("51job·区域销售专员", "https://jobs.51job.com/xinzhengshi/171856350.html"),
    ("51job·博西北区销售经理", "https://jobs.51job.com/zhengzhou/172984462.html"),
    ("BOSS·岗位详情", "https://www.zhipin.com/job_detail/ef329b7baabcec731HF90tS6F1JT.html"),
]


async def probe(label: str, u: str, cfg) -> None:
    host = _host_of(u)
    ok = await _robots_ok(u)
    status, raw_len, title = "-", 0, ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0), follow_redirects=True,
                                      trust_env=False, headers={"User-Agent": FETCH_UA}) as c:
            r = await c.get(u)
            status = r.status_code
            raw_len = len(r.text or "")
            title = ""
            m = __import__("re").search(r"(?is)<title[^>]*>(.*?)</title>", r.text or "")
            if m:
                title = m.group(1).strip()[:60]
    except Exception as e:  # noqa: BLE001
        status = f"{type(e).__name__}"
    text = await _fetch_once(u, cfg.fetcher)
    print(f"{label}  [{host}]")
    print(f"   robots={'允许' if ok else '禁止'}  HTTP={status}  原文={raw_len} 字  title={title or '-'}")
    print(f"   抽取正文={len(text or '')} 字   开头：{(text or '')[:110].replace(chr(10), ' ') or '-'}")
    print()


async def main() -> None:
    cfg = _load_search()
    print(f"fetcher={cfg.fetcher}\n")
    for label, u in URLS:
        await probe(label, u, cfg)


asyncio.run(main())
