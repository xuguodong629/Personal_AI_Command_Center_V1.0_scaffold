"""直接把「材料层」打出来：这些查询到底抓到了哪些页、正文多长、是不是岗位页。

用法（backend 目录）：.\.venv\Scripts\python.exe _tmp_probe_material.py
"""
import asyncio
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.ai import _gather_search, _load_search  # noqa: E402

QUERIES = [
    "site:jobs.51job.com 郑州 区域经理 家电",
    "site:zhaopin.com/jobdetail 郑州 家电 渠道经理",
    "site:zhipin.com/job_detail 郑州 家电 渠道经理",
    "site:liepin.com/job 郑州 家电 区域经理",
    "site:recruit.midea.com 河南 区域经理 招聘",
    "site:maker.haier.net 河南 区域经理 招聘",
    "郑州 家电 渠道经理 招聘",
]


async def main() -> None:
    cfg = _load_search()
    ctx, errs, diag = await _gather_search(cfg, QUERIES, scope="all", per_query=6)
    print(f"引擎={diag.get('engine')}  路数={diag.get('paths')}  结果={diag.get('results')}  "
          f"抓取={diag.get('fetch_note')}")
    print(f"空路={diag.get('empty_paths')}  时间过滤回退={diag.get('no_time_used')}")
    print(f"跳过登录墙={diag.get('skipped_login_walls')}")

    print("\n=== 抓到的网页正文（网页正文块）===")
    for m in re.finditer(r"【网页正文 (\d+)】\n原始链接：(\S+)\n正文：\n(.{0,120})", ctx, re.S):
        idx, url, head = m.group(1), m.group(2), m.group(3).replace("\n", " ")
        print(f"[{idx}] {url}")
        print(f"     {head}")
    n_web = len(re.findall(r"【网页正文 \d+】", ctx))
    print(f"\n正文块共 {n_web} 个；材料总长 {len(ctx)} 字")
    print(f"diag.job_candidates = {diag.get('job_candidates')}")

    print("\n=== 确定性岗位候选清单（系统抽取）===")
    m = re.search(r"【系统确定性抽取的岗位候选清单.*?\n(\|.*?)(?:\n\n|\Z)", ctx, re.S)
    if not m:
        print("  ⚠️ 材料里没有候选清单块！")
    else:
        for ln in m.group(1).splitlines()[:25]:
            print("  " + ln[:200])

    print("\n=== 材料里出现的岗位页 URL（检索摘要部分）===")
    hosts: dict[str, int] = {}
    for u in re.findall(r"https?://[^\s｜]+", ctx):
        h = re.sub(r"^https?://", "", u).split("/")[0]
        hosts[h] = hosts.get(h, 0) + 1
    for h, n in sorted(hosts.items(), key=lambda kv: -kv[1])[:18]:
        print(f"  {h:<34} × {n}")


asyncio.run(main())
