"""测 Serper 免费额度允许哪些查询形态（site: 域名 vs site: 域名+路径 vs 其他）。

用法（backend 目录）：.\.venv\Scripts\python.exe _tmp_probe_site.py
"""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.ai import _load_search, _search_engine  # noqa: E402

FORMS = [
    "郑州 家电 渠道经理 招聘",                      # 基线（无运算符）
    "site:liepin.com 郑州 家电 渠道经理",            # 裸域名
    "site:liepin.com/job 郑州 家电 渠道经理",        # 域名+路径
    "site:zhaopin.com 郑州 家电 渠道经理",
    "site:zhaopin.com/jobdetail 郑州 家电 渠道经理",
    "site:zhipin.com 郑州 家电 渠道经理",
    "site:zhipin.com/job_detail 郑州 家电 渠道经理",
    "site:jobs.51job.com 郑州 家电 渠道经理",
    "site:51job.com 郑州 家电 渠道经理",
    "site:maker.haier.net 河南 销售经理",
    "site:recruit.midea.com 河南 区域经理",
    "inurl:job_detail 郑州 家电 渠道经理",           # 备选：inurl
    '"区域经理" "郑州" 家电 招聘',                    # 备选：精确短语
]


async def main() -> None:
    cfg = _load_search()
    for q in FORMS:
        items, err = await _search_engine(cfg.engine, cfg.api_key, q, count=5, days=0)
        if err:
            flag = "❌"
            note = err[:80]
        else:
            flag = "✅" if items else "⚠️"
            note = f"{len(items)} 条"
            if items:
                note += f"  例：{items[0].get('title', '')[:46]}"
        print(f"{flag} {q}\n     {note}")


asyncio.run(main())
