"""复现雷达里那 6 条空路的真实报错（复刻 count=12/per_query）。

用法（backend 目录）：.\.venv\Scripts\python.exe _tmp_probe_empty.py
"""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.ai import _load_search, _search_engine  # noqa: E402

FAILED = [
    "site:jobs.51job.com 河南 区域经理 家电",
    "site:zhaopin.com/jobdetail 郑州 区域经理 家电",
    "site:zhipin.com/job_detail 新乡 区域经理 家电",
    "site:recruit.midea.com 河南 区域经理 招聘",
    "site:maker.haier.net 河南 区域经理 招聘",
    "site:gree.com.cn 河南 区域经理 招聘",
]


async def main() -> None:
    cfg = _load_search()
    for q in FAILED:
        for count in (5, 12):
            items, err = await _search_engine("serper", cfg.api_key, q, count=count, days=0)
            tag = "❌ 报错" if err else ("⚠️ 0 条" if not items else f"✅ {len(items)} 条")
            print(f"{tag}  count={count:<3} {q}")
            if err:
                print(f"        {err[:110]}")
        print()


asyncio.run(main())
