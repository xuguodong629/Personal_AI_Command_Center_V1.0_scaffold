"""逐条实测检索式：看哪种查询形态能真正召回「河南家电渠道岗」的岗位页。

用法（backend 目录）：.\.venv\Scripts\python.exe _tmp_probe_queries.py
"""
import io
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8787"
QUERIES = [
    "site:jobs.51job.com 河南 区域经理 家电",
    "site:jobs.51job.com 郑州 渠道经理",
    "site:zhaopin.com 郑州 家电 渠道经理",
    "site:zhipin.com/job_detail 郑州 家电 渠道经理",
    "site:liepin.com/job 郑州 家电 区域经理",
    "河南 区域经理 家电 招聘",
    "郑州 家电 渠道经理 招聘 岗位职责 任职要求",
    "美的 社会招聘 河南 区域经理",
    "site:recruit.midea.com 河南",
    "河南 家电 区域经理 12-18K 五险一金 招聘",
]

with httpx.Client(timeout=120.0) as c:
    for q in QUERIES:
        try:
            r = c.post(f"{BASE}/api/search/test", json={"query": q})
            d = r.json()
        except Exception as e:  # noqa: BLE001
            print(f"\n❌ {q}\n   异常 {e}")
            continue
        if not d.get("ok"):
            print(f"\n❌ {q}\n   {d.get('error')}")
            continue
        print(f"\n✅ {q}  → {d.get('count')} 条  ({d.get('latency_ms')}ms) {d.get('note')}")
        for s in d.get("samples") or []:
            print(f"   · {s['title']}")
            print(f"     {s['url']}")
