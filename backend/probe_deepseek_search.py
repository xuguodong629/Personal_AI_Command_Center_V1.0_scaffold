"""探测 DeepSeek API 是否提供联网搜索能力（官方文档说 web_search 内置工具会被忽略，这里实测确认）。

用法（在 backend 目录下）：.\.venv\Scripts\python.exe probe_deepseek_search.py
"""
import io
import json
import sys
from pathlib import Path

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

AI_FILE = Path(__file__).resolve().parents[1] / "data" / "config" / "ai.json"


def load_ds() -> tuple[str, str]:
    providers = json.loads(AI_FILE.read_text("utf-8")) if AI_FILE.exists() else []
    for p in providers:
        if "deepseek" in (p.get("base_url", "") + p.get("name", "")).lower():
            return p["base_url"].rstrip("/"), p["api_key"]
    raise SystemExit("未找到 DeepSeek 供应商配置")


def main() -> int:
    base, key = load_ds()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    print(f"base_url={base}\n")

    # ① Responses API + 内置 web_search 工具（OpenAI 那套托管搜索）
    payload1 = {
        "model": "deepseek-flash",
        "input": "用一句话说出 2026 年郑州家电行业最新的招聘动态，并给出你检索到的来源链接。",
        "tools": [{"type": "web_search"}],
    }
    try:
        r = httpx.post(f"{base}/responses", headers=headers, json=payload1, timeout=120.0, trust_env=False)
        print(f"① POST /responses  + tools=[web_search] → HTTP {r.status_code}")
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        out = json.dumps(body, ensure_ascii=False)
        print(f"   响应中含 web_search_call：{'web_search_call' in out}")
        print(f"   响应中含 url/链接字段：{'url' in out}")
        text = ""
        for item in (body.get("output") or []):
            for c in (item.get("content") or []):
                text += c.get("text", "")
        print(f"   模型回答（前 160 字）：{(text or out)[:160]}")
    except Exception as e:
        print(f"① /responses 失败：{type(e).__name__}: {e}")

    # ② 对话补全 + 同款内置工具
    payload2 = {
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "郑州家电行业最新招聘动态是什么？请给来源链接。"}],
        "tools": [{"type": "web_search"}],
        "stream": False,
    }
    try:
        r = httpx.post(f"{base}/chat/completions", headers=headers, json=payload2, timeout=120.0, trust_env=False)
        print(f"\n② POST /chat/completions + tools=[web_search] → HTTP {r.status_code}")
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        msg = ((body.get("choices") or [{}])[0].get("message") or {})
        print(f"   是否触发工具调用：{'tool_calls' in msg}")
        print(f"   模型回答（前 160 字）：{(msg.get('content') or json.dumps(body, ensure_ascii=False))[:160]}")
    except Exception as e:
        print(f"② /chat/completions 失败：{type(e).__name__}: {e}")

    # ③ 是否存在独立的搜索端点
    for path in ("/web_search", "/search", "/v1/web_search"):
        try:
            r = httpx.post(f"{base}{path}", headers=headers, json={"query": "郑州 区域经理 招聘"}, timeout=30.0, trust_env=False)
            print(f"\n③ POST {path} → HTTP {r.status_code}：{r.text[:120]}")
        except Exception as e:
            print(f"\n③ POST {path} 失败：{type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
