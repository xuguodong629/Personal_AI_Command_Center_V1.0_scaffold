"""合规扩容方向二：第三方招聘 ATS（Moka/北森/51job企业版）能否召回 + 抓取；
以及招聘站检索摘要（snippet）里到底带不带 JD 正文。

用法（backend 目录）：.\.venv\Scripts\python.exe _tmp_probe_ats.py
"""
import asyncio
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.ai import _fetch_page_text, _load_search, _search_engine  # noqa: E402

QUERIES = [
    "site:mokahr.com 河南 区域经理 家电",
    "site:mokahr.com 郑州 渠道经理",
    "site:app.mokahr.com 河南 销售经理",
    "site:hotjob.cn 河南 渠道经理",
    "site:jobs.51job.com 郑州 家电 渠道经理",
    "郑州 家电 渠道经理 招聘",
]
JD_SIGNAL = re.compile(r"(职责|负责|任职|要求|熟悉|经验)")


async def main() -> None:
    cfg = _load_search()
    for q in QUERIES:
        items, err = await _search_engine(cfg.engine, cfg.api_key, q, count=10, days=0)
        print(f"\n=== {q}  → {len(items)} 条" + (f"  err={err[:60]}" if err else ""))
        with_jd = 0
        for it in items[:4]:
            sn = (it.get("content") or "").strip()
            has = bool(JD_SIGNAL.search(sn)) and len(sn) >= 24
            with_jd += 1 if has else 0
            print(f"  [{'摘要含JD' if has else '摘要无JD'}] {it['title'][:44]}")
            print(f"      {it['url'][:96]}")
            print(f"      摘要({len(sn)}字)：{sn[:110]}")
        if items:
            print(f"  → 前 4 条里摘要含 JD 的：{with_jd}/4")
        # ATS 页能不能抓正文
        for it in items[:2]:
            if "mokahr" in it.get("url", "") or "hotjob" in it.get("url", ""):
                t = await _fetch_page_text(it["url"], cfg.fetcher)
                print(f"  [抓取] {it['url'][:70]} → 正文 {len(t or '')} 字"
                      f" {'（含JD词）' if t and JD_SIGNAL.search(t) else ''}")


asyncio.run(main())
