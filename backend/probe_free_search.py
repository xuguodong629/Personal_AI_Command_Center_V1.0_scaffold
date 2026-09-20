"""探测「零 Key 检索方案」在**你这台机器/网络**上是否真的可用。

被测对象：
  ① ddgs（DuckDuckGo，免 Key）
  ② SearXNG 公共实例 JSON API（免 Key）
  ③ 各付费引擎的端点可达性（发无 Key 请求，看到 401/403 说明网络通、只是没 Key）

用法（在 backend 目录下）：.\.venv\Scripts\python.exe probe_free_search.py
"""
import io
import sys
import time

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

QUERY = "郑州 区域经理 招聘"


def test_ddgs() -> None:
    print("① ddgs（DuckDuckGo 免 Key）")
    try:
        from ddgs import DDGS
    except Exception as e:
        print(f"   未安装：{e}")
        return
    t0 = time.time()
    try:
        with DDGS() as d:
            rows = list(d.text(QUERY, region="cn-zh", max_results=5))
        print(f"   ✅ 可用：{len(rows)} 条，{time.time() - t0:.1f}s")
        for r in rows[:3]:
            print(f"      · {r.get('title', '')[:56]} ｜ {r.get('href', '')[:60]}")
    except Exception as e:
        print(f"   ❌ 不可用：{type(e).__name__}: {str(e)[:160]}")


def test_searxng() -> None:
    print("\n② SearXNG 公共实例（免 Key，JSON API）")
    for base in ("https://searx.be", "https://search.bus-hit.me", "https://priv.au", "https://searxng.site"):
        try:
            r = httpx.get(f"{base}/search", params={"q": QUERY, "format": "json"},
                          timeout=12.0, trust_env=False,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; PersonalAIOS/0.6)"})
            ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json")
            n = len((r.json().get("results") or [])) if ok else 0
            print(f"   {base} → HTTP {r.status_code} {'✅ ' + str(n) + ' 条' if ok else '（多为未开放 JSON API）'}")
            if ok and n:
                return
        except Exception as e:
            print(f"   {base} → ❌ {type(e).__name__}: {str(e)[:80]}")


def test_endpoints() -> None:
    print("\n③ 付费引擎端点可达性（无 Key 请求，401/403 = 网络通）")
    probes = [
        ("Tavily", "POST", "https://api.tavily.com/search", {"query": QUERY}),
        ("Serper", "POST", "https://google.serper.dev/search", {"q": QUERY}),
        ("Brave", "GET", "https://api.search.brave.com/res/v1/web/search", None),
        ("博查", "POST", "https://api.bochaai.com/v1/web_search", {"query": QUERY}),
        ("智谱", "POST", "https://open.bigmodel.cn/api/paas/v4/web_search", {"search_query": QUERY}),
    ]
    for name, method, url, body in probes:
        try:
            if method == "GET":
                r = httpx.get(url, params={"q": QUERY}, timeout=12.0, trust_env=False)
            else:
                r = httpx.post(url, json=body, timeout=12.0, trust_env=False)
            print(f"   {name:8} → HTTP {r.status_code} {r.text[:70].replace(chr(10), ' ')}")
        except Exception as e:
            print(f"   {name:8} → ❌ {type(e).__name__}: {str(e)[:80]}")


if __name__ == "__main__":
    test_ddgs()
    test_searxng()
    test_endpoints()
