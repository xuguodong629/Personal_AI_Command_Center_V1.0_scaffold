"""验证：site: 岗位页定向路是否被「发布时间筛选」打成 0 条。

用法（backend 目录）：.\.venv\Scripts\python.exe _tmp_probe_days.py
"""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.ai import _load_search, _search_engine  # noqa: E402

QUERIES = [
    "site:zhaopin.com 郑州 家电 渠道经理",
    "site:liepin.com/job 郑州 家电 区域经理",
    "site:zhipin.com/job_detail 郑州 家电 渠道经理",
    "site:jobs.51job.com 河南 区域经理 家电",
    "郑州 家电 渠道经理 招聘",
]


async def main() -> None:
    cfg = _load_search()
    print(f"engine={cfg.engine} days(cfg)={getattr(cfg, 'days', '?')} max_results={cfg.max_results}")
    for q in QUERIES:
        row = [f"\n{q}"]
        for days in (0, 7, 30):
            items, err = await _search_engine(cfg.engine, cfg.api_key, q, count=5, days=days)
            row.append(f"  days={days:<3} → {len(items):>2} 条" + (f"  err={err[:60]}" if err else ""))
            if items and days == 30:
                row.append(f"        样例：{items[0].get('title', '')[:60]}")
        print("\n".join(row))


asyncio.run(main())
