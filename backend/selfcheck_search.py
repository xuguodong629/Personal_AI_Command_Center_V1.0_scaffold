"""检索层自检：验证「负词不进查询 / 诊断不混进材料 / 空结果放宽重试 / 错误可读」四项。

用桩函数替换真实引擎，离线运行、不消耗任何搜索额度。

用法（在 backend 目录下）：
    .\.venv\Scripts\python.exe selfcheck_search.py
"""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import ai  # noqa: E402

CAPTURED: list[str] = []


def make_stub(behavior: str):
    async def stub(engine, api_key, query, count=5, include_domains="", exclude_domains="", days=0):
        CAPTURED.append(query)
        if behavior == "ok":
            return [{"title": f"岗位 {query[:12]}", "url": f"https://example.com/{len(CAPTURED)}",
                     "content": "区域经理 郑州 五险一金 薪资 10-15K"}], ""
        if behavior == "error":
            return [], "引擎报错：Tavily HTTP 432：This request exceeds your plan's set usage limit."
        if behavior == "empty":
            return [], ""
        if behavior == "partial":
            # 前两路空，其余有结果（用于验证放宽重试）
            if len(CAPTURED) <= 2:
                return [], ""
            return [{"title": "补检索命中", "url": "https://example.com/x", "content": "岗位正文"}], ""
        return [], ""
    return stub


async def case(name: str, behavior: str, queries: list[str]) -> dict:
    CAPTURED.clear()
    ai._search_engine = make_stub(behavior)  # type: ignore[assignment]
    cfg = ai.SearchConfig(engine="tavily", api_key="tvly-test", fallback_engine="none",
                          exclude_keywords="校招, 应届, 实习, 中介, 派遣", max_results=5, fetch_pages=False)
    context, notes, diag = await ai._gather_search(cfg, queries, no_outsourcing=True)
    return {"name": name, "context": context, "notes": notes, "diag": diag, "captured": list(CAPTURED)}


async def main() -> int:
    ok_all = True

    # ① 负词不得进入查询（曾导致零召回）
    r1 = await case("正常", "ok", ["郑州 区域经理 招聘", "河南 渠道经理 招聘"])
    neg_in_query = [q for q in r1["captured"] if " -" in q or q.strip().startswith("-")]
    c1 = not neg_in_query and "[1.1]" in r1["context"] and "无结果" not in r1["context"]
    ok_all &= c1
    print(f"[{'PASS' if c1 else 'FAIL'}] 负词不进查询：捕获查询={r1['captured'][:2]}；命中材料 {r1['diag']['results']} 条")

    # ② 诊断信息不得混进材料（曾导致"有材料"误判 + 生成 0 条报告）
    r2 = await case("全空", "empty", ["郑州 区域经理 招聘", "河南 渠道经理 招聘"])
    c2 = r2["context"].strip() == "" and r2["diag"]["empty_paths"] == 2 and r2["diag"]["results"] == 0
    ok_all &= c2
    print(f"[{'PASS' if c2 else 'FAIL'}] 空结果不产生假材料：context 长度={len(r2['context'])}；空路数={r2['diag']['empty_paths']}")

    # ③ 引擎报错要能被翻译成人话（额度/Key/网络）
    r3 = await case("报错", "error", ["郑州 区域经理 招聘"])
    c3 = ("额度" in r3["diag"]["hint"]) and r3["diag"]["errors"] and r3["context"].strip() == ""
    ok_all &= c3
    print(f"[{'PASS' if c3 else 'FAIL'}] 错误可读：{r3['diag']['hint'][:60]}…")

    # ④ 部分为空 → 用放宽查询补一次
    r4 = await case("部分空", "partial", ["郑州 区域经理 招聘 五险一金", "河南 渠道经理 招聘", "家电 渠道 招聘"])
    c4 = r4["diag"]["relaxed_used"] and r4["diag"]["results"] > 0
    ok_all &= c4
    print(f"[{'PASS' if c4 else 'FAIL'}] 空路放宽重试：{len(r4['diag']['relaxed_used'])} 路补检索；放宽示例={ai._relax_query('郑州 区域经理 招聘 五险一金')!r}")

    # ⑤ 诊断字段完整（前端依赖）
    need = {"engine", "paths", "per_query", "results", "empty_paths", "errors", "hint", "cache_hits"}
    c5 = need.issubset(r1["diag"].keys())
    ok_all &= c5
    print(f"[{'PASS' if c5 else 'FAIL'}] 诊断字段完整：缺失={sorted(need - set(r1['diag'].keys()))}")

    # ⑥ 检索缓存：同一 (引擎+查询+参数) 第二次直接读盘，不再消耗额度
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    ai.SEARCH_CACHE_DIR = tmp
    p = ai._search_cache_path("tavily", "缓存测试查询", 5, 0, [], [])
    items = [{"title": "命中", "url": "https://example.com", "content": "正文"}]
    ai._write_search_cache(p, "tavily", "缓存测试查询", items)
    cached = ai._read_search_cache(p)
    c6 = bool(cached) and cached == items and p.parent == tmp
    ok_all &= c6
    print(f"[{'PASS' if c6 else 'FAIL'}] 检索缓存读写：文件={p.name}；命中 {len(cached or [])} 条")

    print(f"\n结果：{'全部通过' if ok_all else '存在失败项'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
