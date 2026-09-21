"""合规材料源扩容实测：各家电品牌**官方社招站**能不能召回岗位页、正文能不能抓。

只访问公开招聘页；不绕过任何验证码/风控/登录墙。
用法（backend 目录）：.\.venv\Scripts\python.exe _tmp_probe_career.py
"""
import asyncio
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.ai import _fetch_page_text, _host_of, _load_search, _search_engine  # noqa: E402

BRANDS = [
    ("方太", "fotile.com"),
    ("老板电器", "robam.com"),
    ("华帝", "vatti.com.cn"),
    ("格力", "gree.com.cn"),
    ("海信", "hisense.com"),
    ("TCL", "tcl.com"),
    ("九阳", "joyoung.com"),
    ("苏泊尔", "supor.com"),
    ("奥克斯", "auxgroup.com"),
    ("万和", "vanward.com"),
    ("科沃斯", "ecovacs.com"),
    ("美菱", "meiling.com"),
    ("创维", "skyworth.com"),
    ("博西家电", "bsh-group.com"),
]

JD_HINTS = ("职责", "负责", "任职", "要求", "经验", "渠道", "客户")


async def main() -> None:
    cfg = _load_search()
    print(f"{'品牌':<10}{'命中':<6}{'可抓正文页':<12}样例")
    print("-" * 100)
    for name, domain in BRANDS:
        q = f"site:{domain} 河南 区域经理 招聘"
        items, err = await _search_engine(cfg.engine, cfg.api_key, q, count=10, days=0)
        if err:
            print(f"{name:<10}{'报错':<6}{'-':<12}{err[:60]}")
            continue
        jobish = [it for it in items if re.search(r"(job|position|zhaopin|recruit|social|detail|career)", it.get("url", ""), re.I)]
        best = ""
        grab = 0
        for it in (jobish or items)[:3]:
            t = await _fetch_page_text(it["url"], cfg.fetcher)
            if t and len(t) >= 300 and any(h in t for h in JD_HINTS):
                grab += 1
                if not best:
                    best = f"{it['title'][:34]} ｜ 正文 {len(t)} 字"
        print(f"{name:<10}{len(items):<6}{grab:<12}{best or (jobish[0]['url'][:70] if jobish else '无岗位页')}")


asyncio.run(main())
