"""决定性实验：BOSS直聘 / 猎聘 / 智联 / 前程无忧 的**岗位详情页正文**到底抓不抓得到？

只抓公开可索引的页面，不做任何登录绕过；同时检查 robots.txt 是否允许。
用法（backend 目录）：.\.venv\Scripts\python.exe _tmp_probe_fetch.py
"""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.ai import _fetch_page_text, _host_of, _load_search  # noqa: E402

URLS = [
    # 家电渠道岗（真实存在于检索结果里）
    ("BOSS·家电渠道销售-郑州", "https://www.zhipin.com/job_detail/ef329b7baabcec731HF90tS6F1JT.html"),
    ("BOSS·品牌家电门店店长", "https://www.zhipin.com/job_detail/e1f1bdc8670ccbd80nB_3960E1FW.html"),
    ("猎聘·河南亿格电器 郑州大区经理", "https://m.liepin.com/job/1957082659.shtml"),
    ("猎聘·品牌小家电 天猫京东渠道主管", "https://www.liepin.com/job/1985530451.shtml"),
    ("智联·格兰仕 河南分销渠道经理", "https://m.zhaopin.com/jobs/CC302724180J40982752004.htm"),
    ("智联·郑州美学几何 渠道经理", "https://jobs.zhaopin.com/CCL1351485350J40888539713.htm"),
    ("51job·区域销售专员(河南)", "https://jobs.51job.com/xinzhengshi/171856350.html"),
    ("51job·博西家电 北区销售经理", "https://jobs.51job.com/zhengzhou/172984462.html"),
]

JD_HINTS = ("职责", "负责", "任职", "要求", "经验", "学历", "渠道", "客户", "销售", "岗位")


async def main() -> None:
    cfg = _load_search()
    print(f"fetcher={cfg.fetcher}\n")
    for label, u in URLS:
        try:
            text = await _fetch_page_text(u, cfg.fetcher)
        except Exception as e:  # noqa: BLE001
            print(f"❌ {label}\n   {_host_of(u)}  异常：{type(e).__name__} {e}\n")
            continue
        t = (text or "").strip()
        hits = [h for h in JD_HINTS if h in t]
        verdict = "✅ 抓到正文" if len(t) >= 200 else ("⚠️ 极短/疑似拦截页" if t else "❌ 空")
        print(f"{verdict}  {label}")
        print(f"   {_host_of(u)}  长度={len(t)}  命中JD词={len(hits)}/{len(JD_HINTS)} {hits}")
        if t:
            print(f"   开头：{t[:160].replace(chr(10), ' ')}")
        print()


asyncio.run(main())
