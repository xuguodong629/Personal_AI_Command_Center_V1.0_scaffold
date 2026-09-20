"""诊断脚本：直接测搜索引擎，看清到底是谁的问题（Key / 额度 / 负词 / 查询本身）。

用法（在 backend 目录下）：
    .\.venv\Scripts\python.exe diagnose_search.py
"""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.ai import _load_search, _search_engine  # noqa: E402


async def probe(engine: str, key: str, query: str, count: int = 6, tag: str = "") -> None:
    items, err = await _search_engine(engine, key, query, count=count)
    print(f"[{engine}{('/' + tag) if tag else ''}] {len(items)} 条 ｜ err={err or '无'}")
    for it in items[:3]:
        print(f"    · {it['title'][:60]} ｜ {it['url'][:70]}")
    print(f"    query={query[:110]}")
    print()


async def main() -> int:
    cfg = _load_search()
    print(f"配置：engine={cfg.engine} max_results={cfg.max_results} days={cfg.days}")
    print(f"负词（排除关键词）={cfg.exclude_keywords!r}")
    print(f"限定域名={cfg.include_domains!r} 排除域名={cfg.exclude_domains!r}\n")

    clean = "郑州 区域经理 家电 招聘"
    negs = "".join(f" -{w.strip()}" for w in cfg.exclude_keywords.split(",") if w.strip())
    stacked = clean + negs + " -外包 -派遣 -中介 -猎头代招 -校招 -应届 -实习"

    await probe(cfg.engine, cfg.api_key, clean, cfg.max_results, "干净查询")
    await probe(cfg.engine, cfg.api_key, clean + negs, cfg.max_results, "带配置负词")
    await probe(cfg.engine, cfg.api_key, stacked, cfg.max_results, "带全部负词(现状)")
    await probe(cfg.engine, cfg.api_key, "美的集团 河南 招聘", cfg.max_results, "企业定向")
    await probe(cfg.engine, cfg.api_key, "河南 家电 重点产业 规划 扶持 政策", cfg.max_results, "政策路")
    if cfg.fallback_engine not in ("", "none") and cfg.fallback_api_key:
        await probe(cfg.fallback_engine, cfg.fallback_api_key, clean, cfg.max_results, "备用引擎干净查询")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
