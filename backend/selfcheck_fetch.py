"""抓取性能自检：测量「冷启动（首次抓取）」与「热缓存（24h 内重复抓取）」的耗时差异。

用法（在 backend 目录下）：
    .\.venv\Scripts\python.exe selfcheck_fetch.py            # 默认清缓存后测（冷 → 热）
    .\.venv\Scripts\python.exe selfcheck_fetch.py --keep     # 不清缓存，直接测热态

说明：抓取的是**公开政策/媒体页**（不做任何登录墙绕过）。robots 禁止的站点会直接跳过。
"""
import asyncio
import shutil
import sys
import time

from app.ai import PAGE_CACHE_DIR, _fetch_page_text, fetch_stats

URLS = [
    "https://www.gov.cn/zhengce/",
    "https://www.ndrc.gov.cn/",
    "https://www.miit.gov.cn/",
    "https://www.henan.gov.cn/",
    "https://www.stats.gov.cn/",
    "https://www.chinatax.gov.cn/",
]


async def bench(urls: list[str], label: str) -> None:
    before = fetch_stats()
    t0 = time.time()
    texts = await asyncio.gather(*[_fetch_page_text(u) for u in urls])
    dt = time.time() - t0
    after = fetch_stats()
    ok = sum(1 for t in texts if t and t.strip())
    print(
        f"[{label}] 用时 {dt:5.2f}s ｜ 成功 {ok}/{len(urls)} 页 ｜ "
        f"新抓 {after['new'] - before['new']} ｜ 命中缓存 {after['cached'] - before['cached']} ｜ "
        f"robots 禁止 {after['blocked'] - before['blocked']}"
    )


async def main() -> int:
    if "--keep" not in sys.argv:
        shutil.rmtree(PAGE_CACHE_DIR, ignore_errors=True)
    print(f"目标页 {len(URLS)} 个 ｜ 缓存目录 {PAGE_CACHE_DIR}")
    await bench(URLS, "冷启动")
    await bench(URLS, "热缓存")
    await bench(URLS, "热缓存(复测)")
    print(f"缓存文件数：{len(list(PAGE_CACHE_DIR.glob('*.json'))) if PAGE_CACHE_DIR.exists() else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
