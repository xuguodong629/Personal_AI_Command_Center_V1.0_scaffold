"""模型直连路由：供应商配置（OpenAI 兼容协议）+ 连接测试 + 对话代理
+ 三个业务模块的直连编排（定制简历 / 公司背调 / 岗位雷达）。

配置持久化到项目根 data/config/（实施计划 §七.4 的数据目录约定）：
- ai.json     模型供应商列表
- search.json 联网搜索配置（智谱搜索 / Tavily）
支持任何 OpenAI 兼容服务：智谱 GLM / DeepSeek / Ollama / Kimi / 通义 Qwen / OpenAI。
"""
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.archive import save_report
from app.industry import STAGES, evaluate as industry_evaluate, industry_queries, scan_stage
from app.risk import RISK_DIMENSIONS, RiskFacts, evaluate as risk_evaluate, risk_queries
from app.signals import (
    growth_queries,
    policy_queries,
    review_queries,
    scan_growth,
    scan_risk,
    scan_volume,
    volume_rules,
)

router = APIRouter(prefix="/api")

# backend/app/ai.py -> parents[2] = 项目根
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "config"
AI_FILE = DATA_DIR / "ai.json"
SEARCH_FILE = DATA_DIR / "search.json"

CHAT_TIMEOUT = httpx.Timeout(300.0, connect=15.0)
TEST_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
SEARCH_TIMEOUT = httpx.Timeout(25.0, connect=10.0)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 正文抓取：磁盘缓存（同一 URL 24h 内不重复抓）+ 并发上限 + robots 结论缓存
PAGE_CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "pages"
PAGE_CACHE_TTL = 24 * 3600
# 检索结果缓存：同一 (引擎+查询+参数) 24h 内复用，避免重复消耗搜索额度
SEARCH_CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "search"
SEARCH_CACHE_TTL = 24 * 3600
FETCH_UA = "Mozilla/5.0 (compatible; PersonalAIOS/0.5; +local-personal-use)"
_FETCH_SEM = asyncio.Semaphore(6)
_DDG_SEM = asyncio.Semaphore(4)   # DuckDuckGo 免费通道：限制并发，避免被限流封 IP
_ROBOTS: dict[str, bool] = {}
_FETCH_STATS = {"new": 0, "cached": 0, "blocked": 0}
_SEARCH_STATS = {"hits": 0, "miss": 0, "credits": 0}


class Provider(BaseModel):
    id: str
    name: str = "自定义模型"
    base_url: str
    api_key: str = ""
    model: str


class ProviderList(BaseModel):
    providers: list[Provider]


class TestRequest(BaseModel):
    base_url: str
    api_key: str = ""
    model: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    provider_id: str
    messages: list[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class SearchConfig(BaseModel):
    engine: str = "none"  # none | tavily | zhipu | ddg | searxng | mcp | serper | brave | bocha
    api_key: str = ""
    fallback_engine: str = "none"   # 备用引擎：主引擎无结果/报错时自动切换
    fallback_api_key: str = ""
    # 免 Key 检索：ddgs（DuckDuckGo，实测国内可用）/ 自建 SearXNG / 任意 MCP 检索工具
    searxng_url: str = "http://127.0.0.1:8888"   # 自建 SearXNG 地址（需在 settings.yml 开 json 格式）
    mcp_server_id: str = ""     # engine=mcp 时：扩展中心里配置的 MCP 服务器 id
    mcp_tool: str = ""          # engine=mcp 时：检索工具名（如 search / web_search）
    mcp_query_arg: str = "query"  # engine=mcp 时：查询参数名（有的工具叫 q / keyword）
    # ---- 筛选范围 ----
    days: int = 0                 # 时间范围：0=不限 / 1 / 7 / 30（天）
    max_results: int = 5          # 每路检索条数 3–20（越大召回越多，消耗额度也越多）
    include_domains: str = ""     # 限定域名，逗号分隔（Tavily 原生；智谱用 site: 降级）
    exclude_domains: str = ""     # 排除域名，逗号分隔
    exclude_keywords: str = ""    # 排除词，逗号分隔（拼成查询负词）
    # ---- 抓取（新增）----
    fetch_pages: bool = True      # 是否抓取公开页正文（补全 JD 全文）
    fetch_limit: int = 4          # 单次最多抓取页数
    fetcher: str = "auto"         # auto | http | crawl4ai
    skip_login_walls: bool = True # 跳过登录墙平台（BOSS直聘/猎聘等），只保留摘要与直达链接


class DirectResumeRequest(BaseModel):
    provider_id: str
    job_description: str
    resume_text: str = ""


class DirectBgRequest(BaseModel):
    provider_id: str
    company_name: str
    profile: str = ""  # 候选人画像/底线（雇主风险核查透镜）
    mode: str = "full"  # full=16 章节完整背调 / risk=只做风险体检（更快更省）
    deep_risk: bool = True  # 深度风控检索：额外 10 路（空壳/实缴/失信/欠薪/舆情/换壳/税务/破产…）
    facts: dict[str, Any] = {}  # 工商公开事实（界面手填），用于**本地规则层**确定性判定
    manual_material: str = ""   # 手工粘贴的材料：填了就直接跳过搜索引擎，用这些内容分析


class DirectRadarRequest(BaseModel):
    provider_id: str
    position_keywords: str
    regions: str
    industries: str
    resume_summary: str = ""
    profile: str = ""  # 候选人画像 + 优先级 + 底线 + 评分权重（评分依据）
    target_companies: str = ""    # 定向核查的目标企业（逗号分隔）
    # 本次检索的范围筛选（覆盖全局设置）
    scope: str = "all"            # all | job_boards | official | linkedin
    welfare: str = "any"          # any | wuxianyijin（必须五险一金）| wuxian（至少五险）
    no_outsourcing: bool = False  # 排除外包 / 派遣 / 中介
    # 精准筛选档（对齐智联/前程无忧等招聘网站的筛选逻辑）
    company_tier: str = ""        # 公司性质（可多选，逗号分隔）：world500|cn500|industry_leader|foreign|listed|state_owned|private|joint_venture
    salary_min: int = 0           # 月薪下限（元，0=不限）
    salary_max: int = 0           # 月薪上限（元，0=不限）
    exp_years: str = "any"        # any | 1-3 | 3-5 | 5-10 | 10+
    company_size: str = "any"     # any | 0-19 | 20-99 | 100-499 | 500-999 | 1000-9999 | 10000+
    edu: str = "any"              # any | 中专 | 高中 | 大专 | 本科 | 硕士 | 博士
    publish_days: int = 0         # 发布时间：0=不限 / 1 / 3 / 7 / 30（天）
    job_type: str = "any"         # any | 全职 | 兼职 | 实习
    welfare_tags: str = ""        # 福利标签（逗号分隔）：五险一金/双休/包吃住/年终奖…
    # ---- 信号增强（本轮新增，默认全开；关掉可省检索路数与时间）----
    risk_scan: bool = True        # ① 公司风险联动：命中风险关键词直接标注、不给高推荐
    growth_scan: bool = True      # ② 扩张利好：融资/上市/扩产/技术突破/中标 → 是否真在扩人
    review_scan: bool = True      # ③ 雇主口碑：看准/脉脉/知乎/投诉平台评价
    policy_scan: bool = True      # ④ 政策与产业：国家/地方规划、扶持目录、产业链上下游
    # ---- 条数与翻页（本轮新增：一次多出结果，避免反复检索）----
    want_count: int = 20          # 目标机会条数（10/20/30/50，上限 60）
    per_query: int = 0            # 每路检索条数（0=按 want_count 自动计算；1–20）
    batch: int = 0                # 第几批（0=首批；换一批时 +1，用于轮换检索组合）
    skip_seen: str = ""           # 已展示过的「公司·岗位」列表（换一批时排除，避免重复）
    manual_material: str = ""     # 手工粘贴的材料：填了就直接跳过搜索引擎，用这些内容分析


class DirectDeepRequest(BaseModel):
    provider_id: str
    mode: str = "invest"  # invest=投资视角 VC 五步 / screen=优秀企业筛选 6 步
    radar_result: str = ""  # 岗位雷达已生成的机会池文本（分析材料）
    profile: str = ""       # 候选人画像 / 风险偏好（评分依据）


# ---------- 存取 ----------

def _load_providers() -> list[Provider]:
    if not AI_FILE.exists():
        return []
    try:
        return [Provider(**p) for p in json.loads(AI_FILE.read_text("utf-8"))]
    except Exception:
        return []


def _save_providers(items: list[Provider]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AI_FILE.write_text(
        json.dumps([p.model_dump() for p in items], ensure_ascii=False, indent=2),
        "utf-8",
    )


def _load_search() -> SearchConfig:
    if not SEARCH_FILE.exists():
        return SearchConfig()
    try:
        return SearchConfig(**json.loads(SEARCH_FILE.read_text("utf-8")))
    except Exception:
        return SearchConfig()


def _save_search(cfg: SearchConfig) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SEARCH_FILE.write_text(cfg.model_dump_json(indent=2), "utf-8")


# ---------- 错误翻译 ----------

def _error_message(body: str) -> str:
    """尽量从 OpenAI / Tavily 风格错误体中提取 message 字段。"""
    try:
        data = json.loads(body)
        err = data.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(data.get("message"), str):
            return data["message"]
        detail = data.get("detail")
        if isinstance(detail, dict):
            if isinstance(detail.get("error"), str):
                return detail["error"]
            if isinstance(detail.get("message"), str):
                return detail["message"]
        if isinstance(detail, str):
            return detail
    except Exception:
        pass
    return body[:200]


def _translate_status(status: int, body: str) -> str:
    lower = body.lower()
    if status == 402 or "insufficient balance" in lower:
        return "账户余额不足（HTTP 402）。请到对应模型平台充值后重试。"
    if status in (401, 403):
        return f"鉴权失败（HTTP {status}）：API Key 无效、被删除或没有该模型权限。{_error_message(body)}"
    if status == 404:
        return "接口不存在（HTTP 404）：请检查 base_url 是否完整、模型名是否存在。常见坑：智谱是 https://open.bigmodel.cn/api/paas/v4（不带 /v1），DeepSeek/Ollama 才带 /v1。"
    if status == 429:
        return f"请求被限流（HTTP 429）：并发或配额超限，稍后再试。{_error_message(body)}"
    return f"HTTP {status}：{_error_message(body)}"


# ---------- 基础调用 ----------

def _split_list(s: str, limit: int) -> list[str]:
    return [x for x in re.split(r"[\s,，、;；|]+", s or "") if x][:limit]


async def _llm_call_tools(provider: Provider, messages: list[dict], tools: list[dict] | None) -> dict:
    """带工具（function calling）的调用，返回原始 message 对象（可能含 tool_calls）。"""
    url = provider.base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"
    payload: dict[str, Any] = {"model": provider.model, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client:
            res = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"模型调用失败（{type(e).__name__}）：{e}"}
    if res.status_code != 200:
        return {"ok": False, "error": _translate_status(res.status_code, res.text)}
    try:
        msg = res.json()["choices"][0]["message"]
    except Exception:
        return {"ok": False, "error": f"响应格式不符合 OpenAI 协议：{res.text[:200]}"}
    return {"ok": True, "message": msg}


async def _llm_call(provider: Provider, messages: list[dict], timeout: httpx.Timeout = CHAT_TIMEOUT) -> dict:
    """调用 OpenAI 兼容 chat/completions，返回 {ok, content?, error?}。"""
    url = provider.base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"
    payload = {"model": provider.model, "messages": messages, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"模型调用失败（{type(e).__name__}）：{e}"}
    if res.status_code != 200:
        return {"ok": False, "error": _translate_status(res.status_code, res.text)}
    try:
        content = res.json()["choices"][0]["message"]["content"]
    except Exception:
        return {"ok": False, "error": f"响应格式不符合 OpenAI 协议：{res.text[:200]}"}
    if not content or not content.strip():
        return {"ok": False, "error": "模型返回了空内容。"}
    return {"ok": True, "content": content}


# ---- 检索范围与抓取：登录墙平台不做正文抓取（合规优先，仅保留摘要 + 站内直达链接）----
LOGIN_WALL_DOMAINS = ("zhipin.com", "liepin.com", "linkedin.com", "lagou.com", "maimai.cn")
SCOPE_JOB_BOARDS = ["zhaopin.com", "51job.com", "jobui.com", "zhipin.com", "liepin.com"]

# 精准档：企业层级关键词（对齐招聘网站的"公司类型/规模"筛选）
TIER_KEYWORDS = {
    "world500": "世界500强",
    "cn500": "中国500强",
    "industry_leader": "行业头部 龙头",
    "foreign": "外企",
    "listed": "上市公司",
    "state_owned": "国企 央企",
}

# 公司性质中文标签（与 TIER_KEYWORDS 对应；支持多选）
TIER_LABELS = {
    "world500": "世界500强",
    "cn500": "中国500强",
    "industry_leader": "行业头部企业",
    "foreign": "外企",
    "listed": "上市公司",
    "state_owned": "国企/央企",
    "private": "民营",
    "joint_venture": "合资",
}


def _split_csv(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,\s，、;；]+", s or "") if x.strip()]


def _host_of(url: str) -> str:
    return re.sub(r"^https?://", "", url or "").split("/")[0].lower()


def _is_login_wall(url: str) -> bool:
    host = _host_of(url)
    return any(d in host for d in LOGIN_WALL_DOMAINS)


def _scope_domains(cfg: SearchConfig, scope: str) -> tuple[str, str]:
    """按本次范围 + 全局配置计算 (include_domains, exclude_domains)。"""
    inc = _split_csv(cfg.include_domains)
    exc = _split_csv(cfg.exclude_domains)
    if scope == "job_boards":
        inc = list(SCOPE_JOB_BOARDS)
    elif scope == "linkedin":
        inc = ["linkedin.com"]
    elif scope == "official":
        exc += ["zhipin.com", "liepin.com", "lagou.com", "linkedin.com", "51job.com", "zhaopin.com"]
    return ",".join(dict.fromkeys(inc)), ",".join(dict.fromkeys(exc))


async def _search_engine(
    engine: str,
    api_key: str,
    query: str,
    count: int = 5,
    include_domains: str = "",
    exclude_domains: str = "",
    days: int = 0,
    extra: dict[str, Any] | None = None,
) -> tuple[list[dict], str]:
    """调用指定搜索引擎，返回 (结果列表, 错误信息)。错误不再静默丢弃，便于前端显示诊断。

    支持：tavily / zhipu / serper / brave / bocha（后三个用于主引擎额度用尽时切换）。
    结果按 (引擎+查询+参数) 缓存 24 小时：重复检索不再消耗额度。
    """
    if not api_key and engine not in ("ddg", "searxng", "mcp"):
        return [], f"引擎报错：{engine or '未设置'} 未配置 API Key"
    inc = _split_csv(include_domains)
    exc = _split_csv(exclude_domains)

    cache_file = _search_cache_path(engine, query, count, days, inc, exc)
    cached = _read_search_cache(cache_file)
    if cached is not None:
        _SEARCH_STATS["hits"] += 1
        return cached, ""
    _SEARCH_STATS["miss"] += 1

    items: list[dict] = []
    err = ""
    try:
        if engine == "zhipu":
            q = query
            if inc:
                # 智谱无域名参数：用 site: 近似（最多取前两个域名，避免查询过长）
                q = f"{q} ({' OR '.join('site:' + d for d in inc[:2])})"
            if days:
                q = f"{q} 最新"
            async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
                res = await client.post(
                    "https://open.bigmodel.cn/api/paas/v4/web_search",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"search_engine": "search_std", "search_query": q, "count": count},
                )
            if res.status_code != 200:
                return [], f"引擎报错：智谱检索 HTTP {res.status_code}：{_error_message(res.text)}"
            raw = res.json().get("search_result") or []
            items = [
                {
                    "title": it.get("title") or "",
                    "url": it.get("link") or it.get("url") or "",
                    "content": (it.get("content") or "")[:600],
                }
                for it in raw[:count]
            ]
        elif engine == "tavily":
            if not api_key.startswith("tvly-"):
                return [], "引擎报错：Tavily 的 Key 应以 tvly- 开头（当前填的可能是智谱或其他平台的 Key）"
            payload: dict[str, Any] = {
                "api_key": api_key,
                "query": query,
                "max_results": count,
                "search_depth": "basic",
            }
            if inc:
                payload["include_domains"] = inc
            if exc:
                payload["exclude_domains"] = exc
            if days:
                payload["days"] = days
            async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
                res = await client.post("https://api.tavily.com/search", json=payload)
            if res.status_code != 200:
                return [], f"引擎报错：Tavily HTTP {res.status_code}：{_error_message(res.text)}"
            raw = res.json().get("results") or []
            items = [
                {
                    "title": it.get("title") or "",
                    "url": it.get("url") or "",
                    "content": (it.get("content") or "")[:600],
                }
                for it in raw[:count]
            ]
        elif engine == "ddg":
            # DuckDuckGo（免 Key、无需注册）：实测国内网络可用，且能召回 BOSS直聘/猎聘岗位页
            try:
                from ddgs import DDGS  # type: ignore
            except Exception:
                return [], ("引擎报错：未安装 ddgs（免 Key 检索）。安装命令："
                            r".venv\Scripts\pip install ddgs -i https://mirrors.aliyun.com/pypi/simple/")
            tl = {1: "d", 7: "w", 30: "m"}.get(days, "")

            def _run_ddg() -> list[dict]:
                with DDGS() as d:
                    return list(d.text(query, region="cn-zh", safesearch="moderate",
                                       timelimit=tl, max_results=max(5, count)))

            try:
                async with _DDG_SEM:   # 限并发：免费通道别把 IP 打崩
                    rows = await asyncio.to_thread(_run_ddg)   # 同步库丢线程，别阻塞事件循环
            except Exception as e:
                return [], f"引擎报错：ddgs 检索失败（{type(e).__name__}: {e}）"
            items = [
                {
                    "title": r.get("title") or "",
                    "url": r.get("href") or r.get("url") or "",
                    "content": (r.get("body") or "")[:600],
                }
                for r in rows
            ]
            if inc:
                items = [i for i in items if any(d in _host_of(i["url"]) for d in inc)]
            if exc:
                items = [i for i in items if not any(d in _host_of(i["url"]) for d in exc)]
            items = items[:count]
        elif engine == "searxng":
            # 自建 SearXNG（本地聚合百度/必应/搜狗等，完全免费）：需在 settings.yml 打开 json 格式
            base = ((extra or {}).get("searxng_url") or "http://127.0.0.1:8888").rstrip("/")
            params = {"q": query, "format": "json", "language": "zh-CN"}
            if days:
                params["time_range"] = {1: "day", 7: "week", 30: "month"}.get(days, "")
            try:
                async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT, trust_env=False) as client:
                    res = await client.get(f"{base}/search", params=params,
                                           headers={"User-Agent": FETCH_UA})
            except httpx.HTTPError as e:
                return [], (f"引擎报错：连不上自建 SearXNG（{base}）：{type(e).__name__}。"
                            "请确认容器在运行，且 settings.yml 里 search.formats 包含 json。")
            if res.status_code != 200:
                return [], f"引擎报错：SearXNG HTTP {res.status_code}：{_error_message(res.text)}"
            try:
                rows = (res.json().get("results") or [])[:count]
            except Exception:
                return [], ("引擎报错：SearXNG 未返回 JSON（多半是没开 json 格式）。"
                            "在 searxng/settings.yml 的 search.formats 中加入 json 后重启容器。")
            items = [
                {
                    "title": it.get("title") or "",
                    "url": it.get("url") or "",
                    "content": (it.get("content") or "")[:600],
                }
                for it in rows
            ]
        elif engine == "mcp":
            # 把任意 MCP 检索工具接成搜索引擎（扩展中心里配好服务器后，填 server id + 工具名）
            from app.mcp_host import call_tool_direct
            sid = (extra or {}).get("mcp_server_id") or ""
            tool = (extra or {}).get("mcp_tool") or ""
            arg_name = (extra or {}).get("mcp_query_arg") or "query"
            if not sid or not tool:
                return [], "引擎报错：engine=mcp 需要在设置里选择 MCP 服务器与检索工具名"
            args: dict[str, Any] = {arg_name: query, "max_results": count}
            r = await call_tool_direct(sid, tool, args)
            if not r.get("ok"):
                return [], f"引擎报错：MCP 工具调用失败：{str(r.get('error'))[:160]}"
            items = _parse_mcp_search_text(str(r.get("content") or ""), count)
            if not items:
                return [], "引擎报错：MCP 工具返回内容里没解析到链接（可用 /api/mcp/call 看原始返回）"
        elif engine == "serper":
            # serper.dev：Google 结果，免费 2500 次（一次性），header 带 X-API-KEY
            payload = {"q": query, "num": min(count, 20), "gl": "cn", "hl": "zh-cn"}
            if days == 1:
                payload["tbs"] = "qdr:d"
            elif days == 7:
                payload["tbs"] = "qdr:w"
            elif days == 30:
                payload["tbs"] = "qdr:m"
            async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
                res = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                    json=payload,
                )
            if res.status_code != 200:
                return [], f"引擎报错：Serper HTTP {res.status_code}：{_error_message(res.text)}"
            raw = (res.json().get("organic") or [])[:count]
            items = [
                {
                    "title": it.get("title") or "",
                    "url": it.get("link") or "",
                    "content": (it.get("snippet") or "")[:600],
                }
                for it in raw
            ]
        elif engine == "brave":
            # Brave Search API：免费 2000 次/月（country 用大写、search_lang 用 zh-hans，否则会 422）
            params = {"q": query, "count": min(count, 20), "country": "CN", "search_lang": "zh-hans"}
            if days == 1:
                params["freshness"] = "pd"
            elif days == 7:
                params["freshness"] = "pw"
            elif days == 30:
                params["freshness"] = "pm"
            async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
                res = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                    params=params,
                )
            if res.status_code != 200:
                return [], f"引擎报错：Brave HTTP {res.status_code}：{_error_message(res.text)}"
            raw = ((res.json().get("web") or {}).get("results") or [])[:count]
            items = [
                {
                    "title": it.get("title") or "",
                    "url": it.get("url") or "",
                    "content": (it.get("description") or "")[:600],
                }
                for it in raw
            ]
        elif engine == "bocha":
            # 博查 Bocha：国内可用的中文搜索 API，POST /v1/web-search
            async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
                res = await client.post(
                    "https://api.bochaai.com/v1/web-search",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"query": query, "count": min(count, 20), "summary": True, "freshness": "noLimit"},
                )
            if res.status_code != 200:
                return [], f"引擎报错：博查 HTTP {res.status_code}：{_error_message(res.text)}"
            pages = (((res.json().get("data") or {}).get("webPages") or {}).get("value")) or []
            items = [
                {
                    "title": it.get("name") or "",
                    "url": it.get("url") or "",
                    "content": (it.get("summary") or it.get("snippet") or "")[:600],
                }
                for it in pages[:count]
            ]
        else:
            return [], f"引擎报错：未知引擎 {engine}"
    except httpx.HTTPError as e:
        return [], f"引擎报错：网络异常 {type(e).__name__}：{e}"
    except Exception as e:  # 解析异常等，不让整条流水线崩
        return [], f"引擎报错：{engine} 响应解析失败（{type(e).__name__}: {e}）"

    if not err:
        _SEARCH_STATS["credits"] += 1
        _write_search_cache(cache_file, engine, query, items)
    return items, err


def _parse_mcp_search_text(text: str, count: int) -> list[dict]:
    """把 MCP 检索工具返回的文本（各服务器格式不一）尽力解析成标准结果。

    支持三种常见形态：Markdown 链接 `[标题](url)`、标题｜url、裸 URL。
    解析不到就返回空（上层会给出"看原始返回"的提示，不做臆造）。
    """
    if not text:
        return []
    found: list[dict] = []
    for m in re.finditer(r"\[([^\]\n]{2,140})\]\((https?://[^\s)]+)\)", text):
        found.append({"title": m.group(1).strip(), "url": m.group(2), "content": ""})
    for m in re.finditer(r"(?m)^\s*[-*\d.、]*\s*(.{2,140}?)\s*[｜|]\s*(https?://\S+)", text):
        found.append({"title": m.group(1).strip(" -*"), "url": m.group(2).strip(), "content": ""})
    for m in re.finditer(r"(?m)(?:^|\s)(https?://\S{8,})", text):
        found.append({"title": "", "url": m.group(1).rstrip(".,);，。"), "content": ""})

    out: list[dict] = []
    seen: set[str] = set()
    for item in found:
        url = item["url"]
        host_key = url.split("?")[0]
        if host_key in seen:
            continue
        seen.add(host_key)
        if not item["title"]:
            item["title"] = _host_of(url)
        # 取 URL 附近的一段文字当摘要，便于模型判断相关性
        idx = text.find(url[:60])
        if idx >= 0:
            item["content"] = re.sub(r"\s+", " ", text[max(0, idx - 160): idx + 240]).strip()[:400]
        out.append(item)
        if len(out) >= count:
            break
    return out


def _search_cache_path(engine: str, query: str, count: int, days: int,
                       inc: list[str], exc: list[str]) -> Path:
    import hashlib
    key = f"{engine}|{query}|{count}|{days}|{','.join(inc)}|{','.join(exc)}"
    return SEARCH_CACHE_DIR / f"{hashlib.sha1(key.encode('utf-8')).hexdigest()[:20]}.json"


def _read_search_cache(p: Path) -> list[dict] | None:
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text("utf-8"))
        if time.time() - float(data.get("ts", 0)) > SEARCH_CACHE_TTL:
            return None
        items = data.get("items")
        return items if isinstance(items, list) else None
    except Exception:
        return None


def _write_search_cache(p: Path, engine: str, query: str, items: list[dict]) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"engine": engine, "query": query, "ts": time.time(), "items": items},
                                ensure_ascii=False), "utf-8")
    except Exception:
        pass


def search_stats() -> dict[str, int]:
    return dict(_SEARCH_STATS)


def engine_error_hint(errors: list[str]) -> str:
    """把引擎错误翻译成「人话 + 下一步怎么做」。"""
    joined = " ".join(errors)
    if not errors:
        return "检索无结果（查询可能过窄，或该关键词组合没有公开页面）"
    if "SUBSCRIPTION_TOKEN_INVALID" in joined:
        return ("Brave 订阅令牌无效：请到 api-dashboard.search.brave.com → API Keys 复制『Subscription Token』"
                "（不是 App ID / 其他 Key，注意前后别带空格）；也可直接改用免 Key 的 ddg。")
    if "432" in joined or "usage limit" in joined.lower():
        return (
            "Tavily 账户额度已用尽（HTTP 432：超出套餐用量上限）。"
            "免费额度通常每月重置，也可升级套餐；或改用其他引擎（设置 → 搜索引擎：DuckDuckGo(免 Key) / Serper / 博查 / 智谱）。"
        )
    if "余额不足" in joined or "无可用资源包" in joined:
        return "智谱账户余额不足（HTTP 429）：请充值，或改用 DuckDuckGo（免 Key）/ Serper / 博查。"
    if "401" in joined or "403" in joined or "unauthorized" in joined.lower() or "invalid" in joined.lower():
        return "Key 无效或无权限（401/403）：检查 Key 是否填错、是否已过期、是否与该引擎匹配。"
    if "429" in joined:
        return "被限流（HTTP 429）：稍后重试，或换引擎、降低每路结果数。"
    if "未安装" in joined:
        return joined
    if "网络异常" in joined or "连不上" in joined:
        return "网络不可达：检查代理/VPN（本机 localhost 与境外 API 可能被代理劫持），或在设置里改用国内可直连的引擎（DuckDuckGo / 博查 / 智谱）。"
    return "检索引擎报错，详见下方诊断信息。"
    return [], f"引擎报错：未识别的引擎 {engine}"


async def web_search(
    cfg: SearchConfig,
    query: str,
    count: int = 5,
    include_domains: str = "",
    exclude_domains: str = "",
    days: int = 0,
) -> list[dict]:
    """兼容旧签名的薄封装（错误信息丢弃，仅要结果时用）。"""
    items, _err = await _search_engine(
        cfg.engine, cfg.api_key, query, count, include_domains, exclude_domains, days
    )
    return items


async def _fetch_page_text(url: str, fetcher: str = "auto") -> str:
    """抓取公开网页正文（截断 4000 字），带磁盘缓存 / robots 检查 / 一次重试 / 并发限流。

    性能与合规取向（**不做任何绕过登录墙、验证码或风控的"逆向"抓取**）：
    - robots.txt 明确 Disallow: / 的站点直接跳过（读不到 robots 时不阻断，只抓公开页且低频）
    - 页面正文按 URL 哈希缓存 24 小时 → 同一批检索二次运行几乎不重复抓取（实测见 docs/模块/01-岗位雷达.md）
    - 并发上限 6，避免对同一站点造成压力
    crawl4ai 可选：装了就能渲染 JS 页面；没装自动回退 httpx + trafilatura。
    """
    global _FETCH_STATS
    cache_file = _page_cache_path(url)
    cached = _read_page_cache(cache_file)
    if cached is not None:
        _FETCH_STATS["cached"] += 1
        return cached
    if not await _robots_ok(url):
        _FETCH_STATS["blocked"] += 1
        return ""
    async with _FETCH_SEM:
        text = await _fetch_once(url, fetcher)
        if not text:
            text = await _fetch_once(url, fetcher if fetcher == "http" else "http")  # 回退轻量抓取再试一次
    if text:
        _FETCH_STATS["new"] += 1
        _write_page_cache(cache_file, url, text)
    return text


def _page_cache_path(url: str) -> Path:
    import hashlib
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    return PAGE_CACHE_DIR / f"{h}.json"


def _read_page_cache(p: Path) -> str | None:
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text("utf-8"))
        if time.time() - float(data.get("ts", 0)) > PAGE_CACHE_TTL:
            return None
        text = str(data.get("text") or "")
        return text or None
    except Exception:
        return None


def _write_page_cache(p: Path, url: str, text: str) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"url": url, "ts": time.time(), "text": text}, ensure_ascii=False), "utf-8")
    except Exception:
        pass


async def _robots_ok(url: str) -> bool:
    """按 robots.txt 判断该站点是否允许抓取（结果按 host 缓存，一次进程只问一次）。"""
    host = _host_of(url)
    if not host:
        return False
    if host in _ROBOTS:
        return _ROBOTS[host]
    allowed = True
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=4.0), follow_redirects=True, trust_env=False,
            headers={"User-Agent": FETCH_UA},
        ) as client:
            res = await client.get(f"https://{host}/robots.txt")
        if res.status_code == 200:
            txt = res.text[:20000]
            for block in re.split(r"(?im)^\s*user-agent\s*:", txt)[1:]:
                lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
                if lines and lines[0] == "*" and any(
                    re.match(r"(?i)^disallow\s*:\s*/\s*$", ln) for ln in lines[1:]
                ):
                    allowed = False
                    break
    except Exception:
        allowed = True  # robots 取不到时不阻断
    _ROBOTS[host] = allowed
    return allowed


async def _fetch_once(url: str, fetcher: str) -> str:
    """单次抓取（crawl4ai 优先，失败回退 httpx + trafilatura）。"""
    if fetcher in ("auto", "crawl4ai"):
        try:
            from crawl4ai import AsyncWebCrawler  # type: ignore
        except Exception:
            if fetcher == "crawl4ai":
                return ""
        else:
            try:
                async with AsyncWebCrawler(verbose=False) as crawler:
                    res = await crawler.arun(url=url)
                if getattr(res, "success", False):
                    md = getattr(res, "markdown", "")
                    text = md if isinstance(md, str) else getattr(md, "raw_markdown", "")
                    if text and str(text).strip():
                        return str(text).strip()[:4000]
            except Exception:
                pass
    try:
        async with httpx.AsyncClient(
            timeout=SEARCH_TIMEOUT,
            follow_redirects=True,
            trust_env=False,
            headers={"User-Agent": FETCH_UA},
        ) as client:
            res = await client.get(url)
        if res.status_code != 200:
            return ""
        html = res.text
    except httpx.HTTPError:
        return ""
    try:
        import trafilatura  # type: ignore
        return (trafilatura.extract(html, include_comments=False, include_tables=True) or "").strip()[:4000]
    except Exception:
        text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()[:4000]


def fetch_stats() -> dict[str, int]:
    return dict(_FETCH_STATS)


async def _gather_search(
    cfg: SearchConfig,
    queries: list[str],
    scope: str = "all",
    welfare: str = "any",
    no_outsourcing: bool = False,
    per_query: int = 0,
) -> tuple[str, list[str], dict]:
    """并行多路检索 + 抓正文，返回 (材料正文, 诊断条目, 诊断详情)。

    **两个关键约定**（都是踩坑换来的）：
    ① 返回的 `context` 只包含**真正的检索材料**；"无结果/抓取失败"这类说明只进诊断，
       否则上层会误判"有材料"，把诊断当成内容交给模型（曾导致整份报告没有一个岗位）；
    ② **不把排除词拼进查询**：Tavily 等引擎对 `-词` 支持有限，叠加 5 个负词会直接零召回；
       过滤交给提示词层（模型本来就会按"排除外包/校招"处理）。
    """
    include_domains, exclude_domains = _scope_domains(cfg, scope)
    suffix = ""
    if welfare == "wuxianyijin":
        suffix = " 五险一金"
    elif welfare == "wuxian":
        suffix = " 五险"

    final_queries = [f"{q}{suffix}" for q in queries]
    count = max(3, min(20, per_query or cfg.max_results or 5))

    async def run_engine(engine: str, api_key: str, qs: list[str]) -> list[tuple[list[dict], str]]:
        extra = {
            "searxng_url": cfg.searxng_url,
            "mcp_server_id": cfg.mcp_server_id,
            "mcp_tool": cfg.mcp_tool,
            "mcp_query_arg": cfg.mcp_query_arg,
        }
        return await asyncio.gather(
            *[
                _search_engine(
                    engine,
                    api_key,
                    q,
                    count=count,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                    days=cfg.days,
                    extra=extra,
                )
                for q in qs
            ]
        )

    pairs = await run_engine(cfg.engine, cfg.api_key, final_queries)
    engine_errors = [err for _items, err in pairs if err]
    switched = ""
    used_engine = cfg.engine
    # 主引擎全空且配了备用引擎 → 自动切换重试
    if not any(items for items, _e in pairs) and cfg.fallback_engine not in ("", "none") and cfg.fallback_api_key:
        pairs2 = await run_engine(cfg.fallback_engine, cfg.fallback_api_key, final_queries)
        if any(items for items, _e in pairs2):
            pairs = pairs2
            engine_errors = []
            used_engine = cfg.fallback_engine
            switched = f"（主引擎无结果，已自动切换备用引擎：{cfg.engine} → {cfg.fallback_engine}）"
        else:
            engine_errors += [err for _items, err in pairs2 if err]

    # 部分查询为空 → 用「放宽版查询」补一次（去掉多余的限定词，只保留核心词）
    empty_idx = [i for i, (items, _e) in enumerate(pairs) if not items]
    relaxed_used: list[str] = []
    if empty_idx and len(empty_idx) < len(final_queries):
        relaxed_qs = [_relax_query(final_queries[i]) for i in empty_idx]
        pairs3 = await run_engine(used_engine, cfg.api_key if used_engine == cfg.engine else cfg.fallback_api_key, relaxed_qs)
        for pos, (items, err) in zip(empty_idx, pairs3):
            if items:
                pairs[pos] = (items, "")
                relaxed_used.append(final_queries[pos])
            elif err and err not in engine_errors:
                engine_errors.append(err)

    results = [items for items, _err in pairs]

    blocks: list[str] = []
    empty_queries: list[str] = []
    urls: list[str] = []
    for i, (q, items) in enumerate(zip(final_queries, results), 1):
        if not items:
            empty_queries.append(q)
            continue
        parts = [f"【检索 {i}】{q}"]
        for j, it in enumerate(items, 1):
            parts.append(f"[{i}.{j}] {it['title']}｜{it['url']}\n{it['content']}")
            if it.get("url"):
                urls.append(it["url"])
        blocks.append("\n".join(parts))

    # 抓取公开页正文：补全检索摘要看不到的 JD / 公告细节
    skipped: list[str] = []
    cache_note = ""
    if cfg.fetch_pages and urls:
        picked: list[str] = []
        seen: set[str] = set()
        for u in urls:
            host = _host_of(u)
            if not host or host in seen:
                continue
            if cfg.skip_login_walls and _is_login_wall(u):
                skipped.append(host)
                continue
            seen.add(host)
            picked.append(u)
            if len(picked) >= max(0, min(16, cfg.fetch_limit or 4)):
                break
        if picked:
            before = fetch_stats()
            texts = await asyncio.gather(*[_fetch_page_text(u, cfg.fetcher) for u in picked])
            after = fetch_stats()
            web_parts: list[str] = []
            for k, (u, t) in enumerate(zip(picked, texts), 1):
                if t and t.strip():
                    web_parts.append(f"【网页正文 {k}】{u}\n{t.strip()[:3000]}")
            if web_parts:
                blocks.append("\n\n".join(web_parts))
            d_new = after["new"] - before["new"]
            d_cached = after["cached"] - before["cached"]
            d_blocked = after["blocked"] - before["blocked"]
            cache_note = (
                f"正文抓取：新抓 {d_new} 页 / 命中缓存 {d_cached} 页"
                + (f" / robots 禁止 {d_blocked} 页" if d_blocked else "")
                + f"，候选 {len(picked)} 页"
            )

    # 只把**真实材料**放进 context（诊断信息绝不混进去）
    context = "\n\n".join(blocks)
    if context and switched:
        context += f"\n\n{switched}"
    if context and skipped:
        context += f"\n\n（已跳过登录墙平台未抓正文，仅保留检索摘要：{'、'.join(dict.fromkeys(skipped))}）"
    if context and cache_note:
        context += f"\n\n（{cache_note}）"

    stats = search_stats()
    diag = {
        "engine": used_engine,
        "engine_configured": cfg.engine,
        "fallback": cfg.fallback_engine,
        "switched": bool(switched),
        "paths": len(final_queries),
        "per_query": count,
        "results": sum(len(x) for x in results),
        "empty_paths": len(empty_queries),
        "empty_queries": empty_queries[:8],
        "relaxed_used": relaxed_used[:6],
        "errors": list(dict.fromkeys(engine_errors))[:6],
        "hint": engine_error_hint(engine_errors) if not context else "",
        "skipped_login_walls": list(dict.fromkeys(skipped))[:8],
        "fetch_note": cache_note,
        "cache_hits": stats["hits"],
        "cache_miss": stats["miss"],
    }
    return context, list(dict.fromkeys(engine_errors)) + empty_queries, diag


def _relax_query(q: str) -> str:
    """放宽查询：去掉负词与括号，只保留前 4 个语义片段（提高召回，用于空结果的补检索）。"""
    s = re.sub(r"-\S+", " ", q or "")
    s = re.sub(r"[（(][^）)]*[）)]", " ", s)
    parts = [p for p in re.split(r"[\s,，]+", s) if p]
    return " ".join(parts[:4]) or (q or "").strip()


def diag_error_text(diag: dict) -> str:
    """把诊断详情拼成一句可直接展示给用户的错误。"""
    errs = diag.get("errors") or []
    first = errs[0] if errs else "无结果"
    return f"{diag.get('hint') or '联网检索失败'}（引擎={diag.get('engine')}；{first[:160]}）"


def build_manual_context(text: str, max_blocks: int = 40, per_block: int = 3000) -> str:
    """把手工粘贴的材料整理成与检索块同构的上下文。

    用途：搜索额度用尽 / 内网环境 / 想用自己的 DeepSeek App 联网搜完再喂进来时，
    完全跳过搜索引擎，直接走同一套「词库扫描 → 规则层 → 模型分析 → 存档」流水线。
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", raw) if b.strip()]
    if len(blocks) <= 1:
        # 没有空行分隔时按行切，避免一整段 4 万字塞不进上下文
        blocks = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    parts: list[str] = []
    for i, b in enumerate(blocks[:max_blocks], 1):
        parts.append(f"【粘贴材料 {i}】\n{b[:per_block]}")
    total = sum(len(b) for b in blocks)
    head = f"（以下为**用户手工粘贴的材料**，非实时检索；引用时标注 [粘贴k]；原文共 {total} 字，纳入 {min(len(blocks), max_blocks)} 段）"
    return head + "\n\n" + "\n\n".join(parts)


# ---------- 供应商管理 ----------

@router.get("/providers")
def get_providers():
    return {"ok": True, "providers": [p.model_dump() for p in _load_providers()]}


@router.post("/providers")
def set_providers(body: ProviderList):
    _save_providers(body.providers)
    return {"ok": True, "providers": [p.model_dump() for p in body.providers]}


@router.post("/providers/test")
async def test_provider(req: TestRequest):
    url = req.base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if req.api_key:
        headers["Authorization"] = f"Bearer {req.api_key}"
    payload = {
        "model": req.model,
        "messages": [{"role": "user", "content": "请只回复两个字：正常"}],
        "stream": False,
    }
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=TEST_TIMEOUT) as client:
            res = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as e:
        return {
            "ok": False,
            "error": f"无法连接 {url}（{type(e).__name__}）。请确认服务已启动、地址正确、代理设置无误。",
        }
    elapsed = int((time.time() - started) * 1000)
    body = res.text
    if res.status_code != 200:
        return {"ok": False, "error": _translate_status(res.status_code, body)}
    try:
        content = res.json()["choices"][0]["message"]["content"]
    except Exception:
        return {"ok": False, "error": f"响应格式不符合 OpenAI 协议：{body[:200]}"}
    return {"ok": True, "reply": (content or "").strip()[:80], "latency_ms": elapsed}


@router.post("/ai/chat")
async def ai_chat(req: ChatRequest):
    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        return {"ok": False, "error": "模型不存在或已被删除，请重新选择。"}
    r = await _llm_call(provider, [m.model_dump() for m in req.messages])
    if not r.get("ok"):
        return r
    return {"ok": True, "content": r["content"], "model": provider.model}


# ---------- 搜索配置 ----------

@router.get("/search")
def get_search_config():
    return {"ok": True, "search": _load_search().model_dump()}


@router.post("/search")
def set_search_config(cfg: SearchConfig):
    _save_search(cfg)
    return {"ok": True, "search": cfg.model_dump()}


class SearchTestRequest(BaseModel):
    engine: str = ""      # 空=用已保存的配置
    api_key: str = ""
    query: str = "郑州 区域经理 招聘"


@router.post("/search/test")
async def test_search(req: SearchTestRequest):
    """一键自检搜索引擎：一条查询，直接告诉你「能搜到 / 额度用尽 / Key 无效 / 网络不通」。"""
    cfg = _load_search()
    engine = req.engine or cfg.engine
    key = req.api_key or (cfg.api_key if engine == cfg.engine else cfg.fallback_api_key)
    if engine in ("", "none"):
        return {"ok": False, "error": "未选择搜索引擎（设置 → 搜索引擎）。", "engine": engine}
    if not key and engine not in ("ddg", "searxng", "mcp"):
        return {"ok": False, "error": f"{engine} 未填 API Key。", "engine": engine}
    started = time.time()
    extra = {"searxng_url": cfg.searxng_url, "mcp_server_id": cfg.mcp_server_id,
             "mcp_tool": cfg.mcp_tool, "mcp_query_arg": cfg.mcp_query_arg}
    items, err = await _search_engine(engine, key, req.query.strip() or "郑州 区域经理 招聘",
                                      count=5, extra=extra)
    ms = int((time.time() - started) * 1000)
    if err:
        return {
            "ok": False,
            "engine": engine,
            "error": f"{engine_error_hint([err])}（原始信息：{err[:180]}）",
            "raw_error": err,
            "latency_ms": ms,
        }
    return {
        "ok": True,
        "engine": engine,
        "count": len(items),
        "latency_ms": ms,
        "samples": [{"title": it["title"][:70], "url": it["url"][:90]} for it in items[:3]],
        "note": "检索可用" if items else "引擎返回成功但 0 条结果：查询可能过窄，换关键词再试",
    }


# ---------- 直连编排：定制简历（纯 LLM） ----------

RESUME_SYSTEM = (
    "你是一位资深猎头与简历优化专家，熟悉中国家电、消费品、制造业与 B2B 行业的招聘逻辑。"
    "所有输出使用中文 Markdown，结构清晰、信息密度高，不要输出与任务无关的客套话。"
)

def build_resume_user(jd: str, resume: str) -> str:
    # 注意：JD / 简历内容里可能包含大括号（如 JSON），不能用 str.format 拼接
    return (
        "请基于下方【岗位 JD】与【候选人简历】，完成定制简历与匹配分析。\n\n"
        "【岗位 JD】\n"
        f"{jd}\n\n"
        "【候选人简历】\n"
        f"{resume}\n\n"
        "请严格按以下结构输出：\n"
        "# 六维匹配分析\n"
        "用 Markdown 表格评估六个维度（维度 / 匹配度 高·中·低 / 依据）：行业经验、能力技能、业绩成果、管理与跨度、地域与稳定性、发展意愿匹配。\n"
        "# 岗位核心要求解读\n"
        "提炼 5 条以内的关键要求（JD 里真正决定成败的点）。\n"
        "# 定制简历（一岗一版）\n"
        "按目标岗位重写候选人简历：突出匹配的经历与量化成果，弱化无关内容，控制在一页纸篇幅；经历描述使用「动作 + 场景 + 量化结果」句式。\n"
        "# 面试风险与准备建议\n"
        "指出 3-5 个面试官最可能挑战的点，并给出应对建议。"
    )


@router.post("/ai/direct/resume")
async def direct_resume(req: DirectResumeRequest):
    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        return {"ok": False, "error": "模型不存在或已被删除，请重新选择。"}
    user = build_resume_user(
        jd=req.job_description.strip(),
        resume=req.resume_text.strip() or "（未提供，请基于 JD 生成通用优化建议并明确指出需要候选人补充的信息）",
    )
    r = await _llm_call(provider, [
        {"role": "system", "content": RESUME_SYSTEM},
        {"role": "user", "content": user},
    ])
    if not r.get("ok"):
        return r
    return {"ok": True, "content": r["content"], "model": provider.model}


# ---------- 直连编排：公司背调（多路搜索 + 汇总） ----------

BG_SYSTEM = (
    "你是一位 VC 尽调分析师，擅长撰写结构化、可追溯的公司背调报告。"
    "所有输出使用中文 Markdown；只依据提供的检索材料写作，材料未覆盖的部分明确写「公开信息未覆盖」，"
    "不得编造具体数字、日期或事件；报告末尾必须附信息来源清单（引用 [n.m] 编号）。"
)

BG_SECTIONS = """1. 公司概况；2. 工商注册信息；3. 股权结构与实际控制人；4. 主营业务与产品线；5. 行业地位与竞争格局；
6. 经营状况与规模；7. 涉诉情况；8. 行政处罚与合规风险；9. 舆情与口碑；10. 财务状况（公开信息）；
11. 组织与团队；12. 发展战略与近期动态；13. 风险体检矩阵（18 维度表，见要求）；14. 监管问询关注点（若求职视角：雇主风险关注点）；
15. 综合结论与建议；16. 信息来源清单"""

# 风险体检专用系统提示词（mode=risk：只评估风险，不做公司介绍）
BG_RISK_SYSTEM = (
    "你是一位企业风险尽调与雇主风险审查专家，专门识别空壳、套壳、失信、欠薪、涉诉、骗局类风险。"
    "你的立场是**怀疑优先、证据说话**：公开信息查不到就写「待核实」并给出核实路径，绝不替企业背书，也不必客套。"
    "所有输出使用中文 Markdown；只依据提供的检索材料与「本地规则层结论」写作，不得编造具体数字、日期或事件；"
    "引用检索材料时标注 [检索i.j] 编号。**本地规则层给出的数值判定（实缴比例、参保人数、案件数、失信记录等）不得被推翻或淡化。**"
)

BG_RISK_SECTIONS = """一、风险总评（等级 绿/黄/橙/红 + 一句话结论 + 是否触碰一票否决）
二、18 项风险维度矩阵（表格逐行覆盖全部维度：维度 | 结论（命中/未命中/待核实）| 等级 | 依据 | 核实动作）
三、一票否决项核查（表格：项目 | 是否命中 | 依据 | 若命中如何处理；检索中发现的也算，标注「检索层命中」）
四、求职视角 Top5 风险 + 对应面试提问话术（风险 → 一句话话术）
五、待核实清单（公开信息未覆盖的项 + 具体去哪里查，表格）
六、决策建议（继续谈 / 需先核实再谈 / 建议放弃，三档选一 + 3 条以内理由）

【等级规则】本地规则层给出的等级是**下限**：检索材料若出现规则层未覆盖的一票否决级事实（破产重整、失信、欠薪黑名单、招聘收费等），
必须上调等级并说明；不得以「材料未覆盖」为由下调，也不得替企业淡化已知负面。"""


def _risk_block(facts: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """把界面手填的工商事实交给本地规则层，产出确定性结论文本块（供模型引用，不可推翻）。"""
    if not facts:
        return (
            "\n【本地规则层】未提供工商公开事实，本次**未运行确定性规则判定**，"
            "风险结论完全来自公开检索，可信度较低；建议在「风控体检」面板填入工商数据后重跑。\n",
            None,
        )
    res = risk_evaluate(RiskFacts(**facts))
    lines = [
        "\n【本地规则层结论（确定性计算，同输入同输出，不得推翻或淡化）】",
        f"- 风险分：{res['score']}/100 ｜ 等级：{res['level']}（{res['level_hint']}）"
        f" ｜ 一票否决：{'是' if res['veto'] else '否'} ｜ 事实完整度：{int(res['confidence'] * 100)}%",
        f"- 命中统计：一票否决 {res['counts']['veto']} 项 / 高风险 {res['counts']['high']} 项 / "
        f"中风险 {res['counts']['medium']} 项 / 提示 {res['counts']['low']} 项",
    ]
    if res["missing"]:
        lines.append("- 缺失字段（结论置信度受限）：" + "、".join(res["missing"]))
    if res["findings"]:
        lines.append("- 命中红旗清单：")
        for i, f in enumerate(res["findings"], 1):
            lines.append(
                f"  {i}. [{f['severity_label']}] {f['title']}｜依据：{f['detail']}"
                f"｜核实：{f['verify']}" + (f"｜建议：{f['advice']}" if f.get("advice") else "")
            )
    else:
        lines.append("- 未命中任何红旗规则（在已填字段范围内）。")
    lines.append(
        "- 使用要求：以上规则层命中项必须原样出现在你的矩阵与一票否决核查表中；"
        "一票否决项命中时，风险总评等级不得低于「红」，且禁止给出「可以放心入职」类结论。"
        "规则层等级是**下限**：若检索材料发现规则层未覆盖的一票否决级事实（破产重整/失信/欠薪黑名单/招聘收费等），"
        "你必须**上调**总评等级并在表中标注「检索层命中」；任何情况下不得下调规则层给出的等级。\n"
    )
    return "\n".join(lines) + "\n", res


def _risk_matrix_requirement() -> str:
    dims = "；".join(f"{i}. {d['name']}" for i, d in enumerate(RISK_DIMENSIONS, 1))
    return (
        "【18 项风险维度（矩阵须逐行覆盖，不得合并或省略）】\n" + dims + "\n"
    )


def _prepend_prefix(prefix: str, body: str) -> str:
    """把提示横幅加到正文前；若模型已自己复述了横幅（提示词里要求它"先说明"），则不重复。"""
    if not prefix.strip():
        return body
    key = prefix.strip().splitlines()[0].lstrip("> ").strip()[:24]
    if key and key in body:
        return body
    return prefix + body


@router.post("/ai/direct/bgcheck")
async def direct_bgcheck(req: DirectBgRequest):
    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        return {"ok": False, "error": "模型不存在或已被删除，请重新选择。"}
    company = req.company_name.strip()
    risk_mode = (req.mode or "full").strip().lower() == "risk"
    search_cfg = _load_search()
    manual = (req.manual_material or "").strip()

    context = ""
    prefix = ""
    if manual:
        context = build_manual_context(manual)
        diag = {"engine": "manual", "paths": 0, "results": 0, "manual_chars": len(manual),
                "errors": [], "hint": "本次使用手工粘贴材料，未调用搜索引擎"}
        prefix = (
            f"> 📋 本次分析基于**你手工粘贴的材料**（{len(manual)} 字），未调用搜索引擎。"
            "材料未覆盖的部分仍按「材料未见 / 待核实」处理。\n\n"
        )
    elif search_cfg.engine != "none" and search_cfg.api_key:
        if risk_mode:
            queries = risk_queries(company, 12)
        else:
            queries = [
                f"{company} 公司简介 主营业务",
                f"{company} 工商信息 股东 注册资本",
                f"{company} 涉诉 裁判文书 法律风险",
                f"{company} 行政处罚 经营异常",
                f"{company} 最新新闻 动态",
                f"{company} 招聘 规模 发展",
                f"{company} 产品 口碑 评价",
                f"{company} 行业 地位 竞争对手",
            ]
            if req.deep_risk:
                queries += risk_queries(company, 10)
        context, _notes, diag = await _gather_search(search_cfg, queries)
        if not context.strip():
            # 引擎报错且一条材料都没有 → 直接返回可操作的错误，不再烧模型 token 生成"没用的报告"
            if diag.get("errors"):
                return {
                    "ok": False,
                    "error": "联网检索失败，本次无法生成背调报告：" + diag_error_text(diag),
                    "diagnostics": diag,
                    "suggestion": "到「设置 → 搜索引擎」检查 Key/额度，或切换引擎（Tavily / 智谱 / Serper / Brave / 博查）后重试。",
                }
            prefix = (
                "> ⚠️ 联网检索无结果（" + str(diag.get("paths")) + " 路全部为空），"
                "以下内容基于模型既有知识生成，信息可能过时，请谨慎核对。\n\n"
            )
    else:
        diag = {"engine": "none", "paths": 0, "hint": "未启用联网搜索"}
        prefix = "> ⚠️ 未启用联网搜索（设置 → 模型直连 → 搜索引擎），以下内容基于模型既有知识生成，信息可能过时，请谨慎核对。\n\n"

    risk_txt, risk_res = _risk_block(req.facts or {})
    # 检索材料里的风险关键词（确定性词库）：把"公开信息里明说的坏话"直接标出来，防止模型漏读
    sig_risk = scan_risk(context) if context.strip() else []
    sig_growth = scan_growth(context) if context.strip() else []
    sig = {
        "risk": sig_risk,
        "growth": sig_growth,
        "volume": scan_volume(context) if context.strip() else [],
        "volume_rules": volume_rules(context) if context.strip() else [],
    }
    sig["summary"] = {
        "risk_hits": len(sig_risk),
        "risk_veto": sum(1 for x in sig_risk if x.get("severity") == "veto"),
        "risk_high": sum(1 for x in sig_risk if x.get("severity") == "high"),
        "growth_hits": len(sig_growth),
        "fetch": fetch_stats(),
    }
    signals_block = _signals_block(sig, bool(context.strip()), apply="bgcheck")
    if risk_res and risk_res.get("veto"):
        prefix = (
            "> 🚨 **已命中一票否决级风险**（"
            + "、".join(f["title"] for f in risk_res["findings"] if f["severity"] == "veto")
            + "）。以下结论仅供留证与核实，不建议入职或签约。\n\n"
        ) + prefix

    profile_txt = req.profile.strip()
    profile_lens = (
        f"\n【候选人底线（雇主风险核查透镜）】\n{profile_txt}\n\n"
        "在第 14 节与「综合结论与建议」中按候选人底线重点核查："
        "① 渠道费用拖欠 / 回款周期 / 坏账风险信号；② 强压货指标（把区域负责人当压货工具）信号；"
        "③ 渠道与代理体系完整度（渠道政策 / 结算返利 / 培训体系）以及市场是否「无体系、需从零开荒且无资源支持」；"
        "④ 待遇真实性（薪资结构 / 提成占比 / 五险一金基数）。"
        "查到信号逐条列出并标注依据来源；材料未覆盖的写「需在面试/背调中核实」，并给出不冒犯的核实话术。\n"
        if profile_txt else ""
    )

    if risk_mode:
        user = f"""请对公司「{company}」做**风险体检**（只评估风险，不做公司介绍与业务赞美）。

{risk_txt}
{signals_block}
{_risk_matrix_requirement()}
{('以下是实时检索材料，写作时引用 [检索i.j] 编号：' if context else '')}
{context}

【输出要求】固定六节：
{BG_RISK_SECTIONS}
- 第二节矩阵必须逐行覆盖 18 个维度：命中写依据，未命中写「未命中（依据：…）」，查不到写「待核实」。
- 每条判断标注依据编号；规则层命中项必须原样出现，不得改写为「无风险」。
- 表格外的说明每节不超过两行。
{profile_lens}
{('先说明：' + prefix.strip() + chr(10)) if prefix else ''}"""
        system = BG_RISK_SYSTEM
        kind = "风险体检"
    else:
        user = f"""请对公司「{company}」撰写 VC 尽调风格的背调报告（16 章节）。

{risk_txt}
{signals_block}
{_risk_matrix_requirement()}
{('以下是实时检索材料，写作时引用 [检索i.j] 编号：' if context else '')}
{context}

【报告要求】
- 章节固定为：{BG_SECTIONS}
- 第 13 节「风险提示」必须写成**18 项维度矩阵表**（维度 | 结论 | 等级 | 依据 | 核实动作），
  并附「一票否决项核查表」与「待核实清单（去哪查）」；规则层命中的项目必须原样出现。
- 结论部分区分「就业视角」与「合作/投资视角」两段建议，并给出与规则层一致的风险等级（绿/黄/橙/红）。
- 每个结论后标注依据来源编号；材料未覆盖的小节写「公开信息未覆盖」。
{profile_lens}
{('先说明：' + prefix.strip() + chr(10)) if prefix else ''}"""
        system = BG_SYSTEM
        kind = "背调"

    # 去掉多余空行
    user = re.sub(r"\n{3,}", "\n\n", user)

    r = await _llm_call(provider, [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])
    if not r.get("ok"):
        return r
    content = _prepend_prefix(prefix, r["content"])

    meta = {
        "model": provider.model,
        "mode": "risk" if risk_mode else "full",
        "risk_level": (risk_res or {}).get("level", ""),
        "risk_score": (risk_res or {}).get("score", ""),
        "veto": "是" if (risk_res or {}).get("veto") else "",
    }
    archived = {}
    try:
        archived = save_report(company, content, kind=kind, meta=meta, facts=(req.facts or None))
    except Exception as e:  # 存档失败不影响报告返回
        archived = {"ok": False, "error": f"存档失败：{e}"}

    return {
        "ok": True,
        "content": content,
        "model": provider.model,
        "risk": risk_res,
        "signals": sig,
        "archive": archived,
    }


# ---------- 直连编排：岗位雷达（多路搜索 + 评估分档） ----------

def _platform_links(kw: str, region: str) -> str:
    """生成各大招聘平台站内搜索的直达链接（官方站点，点开即见实时岗位与 JD）。"""
    from urllib.parse import quote
    q = quote(f"{kw} {region}")
    return (
        f"[BOSS直聘](https://www.zhipin.com/web/geek/job?query={q}) · "
        f"[猎聘](https://www.liepin.com/zhaopin/?key={q}) · "
        f"[智联招聘](https://sou.zhaopin.com/?kw={q}) · "
        f"[前程无忧](https://we.51job.com/pc/search?keyword={q}) · "
        f"[领英](https://www.linkedin.com/jobs/search/?keywords={q})"
    )

RADAR_SYSTEM = (
    "你是一位经验丰富的招聘顾问，擅长评估岗位质量、企业质量与候选人匹配度。"
    "评估机会时遵循用户的筛选偏好："
    "① 企业质量优先级：外企、世界500强、中国500强、地区龙头/优秀企业优先；"
    "② 福利保障优先级：五险一金最优先，次之五险，未提及或无保障的在材料中如实标注；"
    "③ 对「同一公司同一或相似岗位在不同平台重复发布、或常年长期挂出」的情况做刷 KPI（虚假/凑数招聘）嫌疑判断；"
    "④ 行业优先：与候选人目标行业（画像中的行业背景）一致的岗位优先；"
    "**行业明显不符的岗位（如医疗、种业、农业、金融保险、纯互联网、地产等）一律降为低推荐或直接排除**，"
    "即使岗位名称或薪资好看；排在表格后段并注明「行业不符」。"
    "⑤ 只为有稳定从业经历的社招候选人筛选：校招、应届生、实习生岗位直接排除并注明「校招/届别不符」。"
    "⑥ 联系方式合规红线：只能原样引用检索材料中**已公开招聘**的联系方式（招聘邮箱、公司总机、招聘页公开的联系人称呼）；"
    "**严禁推断、拼接、猜测电话号码，严禁输出任何个人手机号**；公司负责人只输出公开渠道可查的姓名与职务，并给核查路径。"
    "所有输出使用中文 Markdown；只依据提供的检索材料整理机会，材料未覆盖的部分明确说明，"
    "不得编造具体的在招岗位、薪资与联系人信息；每条判断尽量给出依据（引用 [检索i.j] 编号，或明确写「材料未覆盖」）。"
)


def _signals_block(sig: dict[str, Any], has_context: bool, apply: str = "radar") -> str:
    """把确定性词库命中整理成提示词块（强制模型落位到表格，不允许忽略）。"""
    if not has_context:
        return ""
    risk, growth, vol, rules = sig.get("risk") or [], sig.get("growth") or [], sig.get("volume") or [], sig.get("volume_rules") or []
    if not (risk or growth or vol or rules):
        return (
            "\n【本地信号扫描（确定性词库）】本次材料未命中任何风险/利好/刷量关键词。"
            "注意：未命中 ≠ 无风险，只表示材料里没有这些字眼，仍须按维度核查。\n"
        )
    lines = ["\n【本地信号扫描（确定性词库命中；这是事实而非推测，必须逐条落位到表格）】"]

    def _line(items: list[dict], label: str, key: str = "dimension") -> str:
        parts = []
        for it in items[:12]:
            tag = it.get(key) or it.get("type") or it.get("signal") or ""
            parts.append(f"{it['keyword']}×{it['count']}" + (f"（{tag}）" if tag else ""))
        return f"- {label} {len(items)} 项：" + "、".join(parts)

    if risk:
        veto = [x for x in risk if x.get("severity") == "veto"]
        lines.append(_line(risk, "公司风险关键词命中"))
        if veto:
            lines.append("  · **一票否决级命中**：" + "、".join(f"{x['keyword']}（{x['meaning']}）" for x in veto[:6]))
        # 关键片段（最多 3 条，给模型可引用的原话）
        for it in risk[:3]:
            if it.get("snippet"):
                lines.append(f"  · 原话片段（{it['keyword']}）：{it['snippet'][:120]}")
    if growth:
        lines.append(_line(growth, "扩张利好信号", "type"))
    if vol:
        lines.append(_line(vol, "刷量/虚假招聘关键词", "signal"))
    for r in rules[:5]:
        lines.append(f"- 计数型刷量线索：{r['signal']}｜{r['detail']}")
    if apply == "bgcheck":
        lines.append(
            "【落位要求（违反视为不合格输出）】\n"
            "① 上面的命中项必须写进报告对应的风险维度与「风险体检矩阵」中，写清关键词与依据编号；\n"
            "② 命中一票否决级风险（失信/破产/欠薪/跑路/收费/传销）时，总评等级不得低于「红」，"
            "并在报告开头显著提示；\n"
            "③ 关键词命中只是线索：需注明来源与性质（公开检索/待核实），不要把它当成已生效的法律结论；\n"
            "④ 命中扩张利好时，说明「利好是否真的对应扩编」，并给核实动作。"
        )
    else:
        lines.append(
            "【落位要求（违反视为不合格输出）】\n"
            "① 上面的命中项必须逐条出现在表四（风险·刷量·口碑）中，写清关键词与依据编号；\n"
            "② 命中一票否决级风险（失信/破产/欠薪/跑路/收费/传销）的岗位，表一「级」列最高只能给"
            "「低⚠️公司风险」并写出风险关键词，**严禁进入优先投递**；\n"
            "③ 命中扩张利好的公司，在表五判断「是否真的在扩人」（利好 → 招聘规模扩张，要有依据支撑，"
            "不能拿「公司很大」当扩张证据）；\n"
            "④ 命中刷量线索的岗位，表一标「中⚠️刷量」或「低⚠️刷量」，表四给核实动作；\n"
            "⑤ 不得因为薪资好看、公司名气大而忽略以上命中；材料矛盾时以关键词命中的原文为准并标注冲突。"
        )
    return "\n".join(lines) + "\n"


def _extract_pool_rows(content: str) -> list[dict[str, str]]:
    """从机会池报告里解析「表一」的**整行**（含级/岗位/公司/薪资/风险标记/JD 要点等全部列）。

    只做机械解析：找到含「岗位」与「公司」的表头行，按列名取单元格。
    解析失败返回空列表（不阻断，只是前端拿不到结构化数据）。
    """
    rows: list[dict[str, str]] = []
    lines = content.splitlines()
    header: list[str] | None = None
    for ln in lines:
        if not ln.strip().startswith("|"):
            if header:  # 表一结束
                break
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if header is None:
            if any(c == "岗位" for c in cells) and any(c == "公司" for c in cells):
                header = cells
            continue
        if all(set(c) <= set("-: ") for c in cells):  # 分隔行
            continue
        if len(cells) < len(header):
            continue
        row = {header[i]: cells[i] for i in range(len(header))}
        post = row.get("岗位", "")
        comp = row.get("公司", "")
        if post and comp and comp != "公司":
            rows.append(row)
        if len(rows) >= 200:
            break
    return rows


def _extract_score_map(content: str) -> dict[str, dict[str, str]]:
    """解析「表二 · 加权评分总览」，返回 {公司/机会: {总分, 分层}}（用于给表一挂分数）。"""
    out: dict[str, dict[str, str]] = {}
    lines = content.splitlines()
    header: list[str] | None = None
    for ln in lines:
        if not ln.strip().startswith("|"):
            if header:
                break
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if header is None:
            if any("总分" in c for c in cells) and any("分层" in c for c in cells):
                header = cells
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) < len(header):
            continue
        row = {header[i]: cells[i] for i in range(len(header))}
        key = next((v for k, v in row.items() if k and ("公司" in k or "机会" in k)), "")
        if not key:
            continue
        score = next((v for k, v in row.items() if k and "总分" in k), "")
        layer = next((v for k, v in row.items() if k and "分层" in k), "")
        out[key] = {"score": score, "layer": layer}
    return out


def _attach_scores(items: list[dict[str, str]], scores: dict[str, dict[str, str]]) -> None:
    """把表二的加权总分/分层按公司名模糊匹配挂到表一行上（匹配不到就留空，不猜）。"""
    for it in items:
        comp = (it.get("公司") or "").strip()
        post = (it.get("岗位") or "").strip()
        if not comp or comp.startswith("材料未见"):
            continue
        best: dict[str, str] | None = None
        for key, val in scores.items():
            if comp and (comp in key or key.split("·")[0].strip() in comp):
                best = val
                break
        if best is None and post:
            for key, val in scores.items():
                if post[:6] and post[:6] in key:
                    best = val
                    break
        if best:
            it["_score"] = best.get("score", "")
            it["_layer"] = best.get("layer", "")


def _rows_block(rows: list[dict[str, str]], limit: int = 60) -> str:
    if not rows:
        return ""
    items = "；".join(f"{r.get('公司', '')}·{r.get('岗位', '')}" for r in rows[:limit])
    return f"\n【本批已展示过、下一批必须排除的条目】\n{items}\n"


@router.post("/ai/direct/radar")
async def direct_radar(req: DirectRadarRequest):
    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        return {"ok": False, "error": "模型不存在或已被删除，请重新选择。"}
    # 全量清单（用于提示词，保证"全选"不被截断）与检索用子集（8 路查询预算内）
    kw_all = _split_list(req.position_keywords, 30)
    region_all = _split_list(req.regions, 120)
    ind_all = _split_list(req.industries, 60)
    kws = kw_all[:6]
    regions = region_all[:6]
    inds = ind_all[:4]
    regions_query = regions[:4]   # 区域查询最多 4 路，给企业/层级/官网留出名额

    def _brief(items: list[str], keep: int = 60) -> str:
        """清单过长时截断展示，避免提示词膨胀。"""
        if len(items) <= keep:
            return '、'.join(items)
        return '、'.join(items[:keep]) + f' …等共 {len(items)} 项'
    if not kws:
        return {"ok": False, "error": "岗位关键词为空。"}

    kw0 = kws[0]
    # 平台站内直达检索链接：不依赖搜索引擎召回，保证结果里有能点开的真实岗位入口
    rg_top = regions[:2]
    links_block = (
        "\n【平台站内直达检索（官方站点，点开即见实时岗位与 JD）】\n"
        + "\n".join(f"- **{rg} · {kw0}**\n  {_platform_links(kw0, rg)}" for rg in rg_top)
        + "\n"
        if rg_top
        else ""
    )

    search_cfg = _load_search()
    # 发布时间：本次筛选优先（对齐招聘网站的"发布时间"筛选）
    if req.publish_days and req.publish_days > 0:
        search_cfg = search_cfg.model_copy(update={"days": req.publish_days})
    welfare_extra = " ".join(_split_csv(req.welfare_tags)[:3])
    companies = _split_csv(req.target_companies)[:8]
    queries: list[str] = []
    if search_cfg.engine != "none" and search_cfg.api_key:
        ind0 = inds[0] if inds else ""
        # 1) 区域 × 岗位 × 行业锚点（行业必须进查询，否则召回全是无关行业）
        for rg in regions_query:
            queries.append(f"{rg} {kw0} {ind0} 招聘".strip())
        # 2) 目标企业定向核查（候选人重点关注的品牌方）
        for c in companies[:3]:
            rg0 = regions[0] if regions else "河南"
            queries.append(f"{c} {rg0} {kw0} 招聘")
        if companies:
            queries.append(f"{' '.join(companies[:6])} {kw0} 招聘 官网")
        # 3) 精准档：公司性质（可多选：世界500强 / 中国500强 / 行业头部 / 外企 / 上市 / 国企 / 民营 / 合资）
        tier_keys = [k for k in _split_csv(req.company_tier) if k in TIER_KEYWORDS]
        tier_kw = " ".join(TIER_KEYWORDS[k] for k in tier_keys[:3])
        if tier_kw:
            rg0 = regions[0] if regions else "河南"
            queries.append(f"{rg0} {tier_kw} {ind0} {kw0} 招聘".strip())
        # 4) 招聘网站式硬条件（职位类型 / 经验 / 学历 / 规模 / 薪资 / 福利标签）
        hard_bits: list[str] = []
        if req.job_type not in ("", "any"):
            hard_bits.append(req.job_type)
        if req.exp_years not in ("", "any"):
            hard_bits.append(f"{req.exp_years}年经验")
        if req.edu not in ("", "any"):
            hard_bits.append(req.edu)
        if req.company_size not in ("", "any"):
            hard_bits.append(f"{req.company_size}人")
        if req.salary_min and req.salary_max:
            hard_bits.append(f"{req.salary_min // 1000}-{req.salary_max // 1000}K")
        if hard_bits:
            queries.append(f"{kw0} {ind0} {' '.join(hard_bits)} 招聘".strip())
        # 5) 福利标签专路
        if welfare_extra:
            queries.append(f"{kw0} {ind0} {welfare_extra} 招聘".strip())
        # 5) 企业质量优先：外企 / 世界500强 / 中国500强（带行业锚点）
        if regions:
            queries.append(f"{regions[0]} 外企 世界500强 {ind0} {kw0} 招聘".strip())
        # 6) 企业官网直招 + 福利线索
        if inds:
            queries.append(f"{kw0} {'/'.join(inds[:2])} 公司 官网 招聘 五险一金")
        # 7) 职业/社交平台：领英 LinkedIn（带行业）
        queries.append(f"linkedin {kw0} {ind0} {'/'.join(regions[:2])} jobs".strip())
        # 8) 公司风险联动路（失信/被执行/欠薪/投诉 → 直接标注，不让"看着香"的岗位进推荐位）
        if req.risk_scan:
            rg0 = regions[0] if regions else "河南"
            queries.append(f"{rg0} {ind0} 公司 欠薪 失信 被执行 投诉 劳动仲裁".strip())
        # 9) 扩张利好路（融资 / 上市 / 扩产 / 技术突破 / 中标 → 判断是否真在扩人）
        if req.growth_scan:
            queries += growth_queries(companies, regions, inds)
        # 10) 雇主口碑路（看准 / 脉脉 / 知乎 / 黑猫投诉）
        if req.review_scan:
            queries += review_queries(companies, regions, inds)
        # 11) 政策与产业规划路（国家/地方规划、扶持目录、产业链上下游）
        if req.policy_scan:
            queries += policy_queries(regions, inds)
        # 去重并截断（批次数越大路数越多：换一批时要覆盖新的组合，而不是重复同一批）
    seen: set[str] = set()
    uniq: list[str] = []
    for q in queries:
        if q and q not in seen:
            seen.add(q)
            uniq.append(q)
    want = max(5, min(60, req.want_count or 20))
    # 每路条数：目标条数越多，单路召回越多（上限 20，受引擎限制）
    per_query = max(3, min(20, req.per_query or (5 if want <= 15 else min(20, max(5, round(want / 3 + 2))))))
    # 路数上限：基础 14 路，条数需求大时最多扩到 20 路（按 batch 轮换区域/行业组合，避免每次同一批）
    max_paths = 14 if want <= 20 else (17 if want <= 30 else 20)
    if want > 20 and regions and inds:
        offset = (req.batch or 0) % max(len(regions), 1)
        rotated = regions[offset:] + regions[:offset]
        for rg in rotated[4:]:
            uniq.append(f"{rg} {kw0} {ind0} 招聘".strip())
            if len(uniq) >= max_paths:
                break
        for ind in inds:
            if ind == ind0:
                continue
            uniq.append(f"{regions[0] if regions else '河南'} {kw0} {ind} 招聘 五险一金".strip())
            if len(uniq) >= max_paths:
                break
    queries = uniq[:max_paths]

    context = ""
    engine_errs: list[str] = []
    diag: dict[str, Any] = {"engine": search_cfg.engine, "paths": len(queries), "errors": []}
    manual = (req.manual_material or "").strip()
    if manual:
        # 手工粘贴模式：完全跳过搜索引擎（零额度也能跑），材料同样进词库扫描与规则层
        context = build_manual_context(manual)
        diag = {"engine": "manual", "paths": 0, "per_query": 0, "results": 0,
                "manual_chars": len(manual), "errors": [], "hint": "本次使用手工粘贴材料，未调用搜索引擎"}
    elif queries:
        context, engine_errs, diag = await _gather_search(
            search_cfg,
            queries,
            scope=req.scope,
            welfare=req.welfare,
            no_outsourcing=req.no_outsourcing,
            per_query=per_query,
        )
        # 引擎报错且零材料 → 直接失败并给出可操作提示（不生成"0 条机会池"的空报告，也不烧模型 token）
        if not context.strip() and diag.get("errors"):
            return {
                "ok": False,
                "error": "联网检索失败，本次无法生成机会池：" + diag_error_text(diag),
                "diagnostics": diag,
                "suggestion": "去「设置 → 搜索引擎」检查额度/Key，或换引擎（Tavily / 智谱 / Serper / Brave / 博查）后重试；"
                              "也可以把你在 DeepSeek App / 浏览器搜到的内容粘到「手工粘贴材料」里，零额度照样能分析。",
            }
    elif search_cfg.engine in ("", "none"):
        diag["hint"] = "未启用联网搜索"

    # ---- 本地信号扫描（确定性词库，不依赖模型）----
    sig: dict[str, Any] = {"risk": [], "growth": [], "volume": [], "volume_rules": []}
    if context.strip():
        if req.risk_scan:
            sig["risk"] = scan_risk(context)
        if req.growth_scan:
            sig["growth"] = scan_growth(context)
        sig["volume"] = scan_volume(context)
        sig["volume_rules"] = volume_rules(context)
    sig["summary"] = {
        "risk_hits": len(sig["risk"]),
        "risk_veto": sum(1 for x in sig["risk"] if x.get("severity") == "veto"),
        "risk_high": sum(1 for x in sig["risk"] if x.get("severity") == "high"),
        "growth_hits": len(sig["growth"]),
        "volume_hits": len(sig["volume"]),
        "volume_rules": len(sig["volume_rules"]),
        "paths": len(queries),
        "engine": diag.get("engine"),
        "fetch": fetch_stats(),
        "search": search_stats(),
    }
    # 政策与产业规划检索路（回传前端，可复制自查；政策文件原文比模型转述更可靠）
    sig["policy_queries"] = policy_queries(regions, inds) if req.policy_scan else []
    signals_block = _signals_block(sig, bool(context.strip()))

    profile_txt = req.profile.strip()
    profile_section = (
        f"\n【候选人画像与匹配标准（评分依据，务必遵守）】\n{profile_txt}\n\n"
        if profile_txt else ""
    )
    scoring_note = (
        "\n【评分与分层要求】对每条机会按画像权重逐项打分（0-100）：\n"
        "- 输出一张总览表：公司/机会 | 加权总分 | 分层(优先投递/谨慎/直接排除) | 命中底线(是/否) | 关键依据\n"
        "- 分层：≥80 优先投递；60–79 谨慎；<60 直接排除；命中任一条底线直接排除（注明命中哪条）\n"
        "- 材料覆盖不到的维度如实标低分并注明「待核实：去哪查/问谁」；不要臆造企业实况\n"
        if profile_txt else ""
    )
    scope_label = {"all": "不限", "job_boards": "招聘平台", "official": "企业官网与公告", "linkedin": "领英"}.get(req.scope, req.scope)
    welfare_label = {"any": "不限", "wuxianyijin": "必须五险一金", "wuxian": "至少五险"}.get(req.welfare, req.welfare)
    filter_note = (
        f"\n【本次筛选范围】平台范围={scope_label}；"
        f"时间范围={('近 ' + str(search_cfg.days) + ' 天') if search_cfg.days else '不限'}；"
        f"保障要求={welfare_label}{'；已排除外包/派遣/中介' if req.no_outsourcing else ''}"
        + (f"；定向核查企业：{req.target_companies.strip()}" if req.target_companies.strip() else "")
        + "\n"
    )
    tier_keys = _split_csv(req.company_tier)
    tier_label = " / ".join(TIER_LABELS.get(k, k) for k in tier_keys) or "不限"
    if len(tier_keys) > 1:
        tier_label += "（多选，满足任一即可）"
    bits = [f"公司性质={tier_label}"]
    if req.salary_min or req.salary_max:
        bits.append(f"月薪范围={req.salary_min or '不限'}–{req.salary_max or '不限'} 元")
    if req.exp_years not in ("", "any"):
        bits.append(f"经验要求={req.exp_years} 年")
    if req.company_size not in ("", "any"):
        bits.append(f"公司规模={req.company_size} 人")
    if req.edu not in ("", "any"):
        bits.append(f"学历要求≤{req.edu}")
    if req.publish_days:
        bits.append(f"发布时间=近 {req.publish_days} 天")
    if req.job_type not in ("", "any"):
        bits.append(f"职位类型={req.job_type}")
    if req.welfare_tags.strip():
        bits.append(f"福利标签={req.welfare_tags.strip()}")
    precise_note = (
        "\n【本次硬性筛选条件（对齐招聘网站筛选逻辑；不满足者降为低推荐或直接排除，并注明原因）】"
        + "；".join(bits)
        + "\n材料未覆盖的条件写「材料未覆盖」，不得因公司名气或岗位名称好听而忽略这些条件。"
        + f"本次共 {max(8, len(queries))} 路检索（含风险联动 / 扩张利好 / 雇主口碑 / 政策产业规划）："
        + "所选区域/关键词/行业较多时只覆盖部分组合，其余按上方全量清单判断，"
        + "并在来源清单的备注列标注「本次未检索」。\n"
    )

    # ---- 本批数量与去重要求（用户可选 10/20/30/50 条；换一批时排除已展示项）----
    count_note = (
        f"\n【本批数量要求】目标输出 **{want}** 条机会（第 {int(req.batch or 0) + 1} 批）。"
        f"表一行数应尽量达到 {want} 条；若检索材料不足以支撑，就输出材料能支撑的全部条目，"
        "并在表一前用一行说明「本批材料仅支撑 N 条，缺口原因：材料未覆盖具体岗位 / 该区域在招量少 / 需放宽筛选」。\n"
        "【去重与排序规则】\n"
        "- 同一公司 + 同一（或高度相似）岗位在不同平台重复出现的，**合并为一行**，链接列放多个来源编号；\n"
        "- 同一公司最多保留 3 条（不同岗位/不同区域可各占一行），避免一家公司刷满整张表；\n"
        "- 表一按「级」再按表二加权总分降序排列，优先投递的排最前；\n"
        "- 每条必须给出可点开的链接或平台站内直达指引（材料无 url 时用平台检索链接并标注「需站内检索」）。\n"
    )
    skip_items = [x.strip() for x in re.split(r"[;；\n]+", req.skip_seen or "") if x.strip()][:80]
    if skip_items:
        count_note += (
            "\n【本批必须排除（上一批已展示过，不得重复出现）】\n"
            + "；".join(skip_items)
            + "\n如需再次提及，最多在表格外一行说明「上批已列 N 条」。\n"
        )

    if not context.strip():
        disclaimer = (
            "> ⚠️ **未启用联网搜索（或检索无结果）**：本次无实时在招岗位与来源链接。"
            "启用方法：设置 → 模型直连 → 搜索引擎（智谱搜索或 Tavily，二选一填 Key）→ 保存 → 重新搜索。"
            "以下为基于模型知识的方向性建议（行业、区域、目标企业类型与投递渠道），并附「去哪查到具体岗位」的直达指引。"
            + ("\n> **检索诊断**：" + "；".join(dict.fromkeys(engine_errs)) if engine_errs else "")
            + "\n\n"
        )
        user = f"""候选人画像：{req.resume_summary.strip() or '（未提供）'}
目标岗位关键词：{_brief(kw_all)}
目标区域：{_brief(region_all) or '不限'}
目标行业：{_brief(ind_all) or '不限'}

{profile_section}{filter_note}{precise_note}{signals_block}请输出 Markdown 求职机会分析，**全部用表格呈现，禁止大段散文**：

## 表一 · 区域与行业机会评估
| 区域 | 行业 | 推荐度 | 政策与产业支持（国家/地方规划、扶持目录） | 上下游机会 | 理由 |

## 表二 · 建议关注的公司与渠道（优先外企 / 世界500强 / 中国500强 / 地区优秀企业）
| 类别 | 代表企业 | 扩张利好（融资/上市/扩产/中标） | 雇主口碑（看准/脉脉/投诉平台） | 投递渠道 | 入口/链接 |

## 表三 · 具体岗位检索指引
{links_block}
| 平台 | 站内检索词 | 直达链接 |

## 表四 · 福利保障核查要点
| 核查项 | 问谁 / 怎么问 | 红旗信号 |

## 表五 · 风险 · 刷量 · 口碑 综合判定
| 公司/机会 | 公司风险（关键词 + 结论） | 刷量/虚假招聘（结论 + 依据） | 雇主口碑（评价与主题） | 建议核实动作 |

## 表六 · 政策与产业匹配（国家 / 地方）
| 政策/规划文件 | 层级（国家/省/市） | 支持方向 | 与目标岗位的关系 | 受益企业与上下游 | 来源 |

## 表七 · 求职策略与下一步
| 步骤 | 动作 | 时间 |
{scoring_note}"""
    else:
        disclaimer = ""
        user = f"""候选人画像：{req.resume_summary.strip() or '（未提供）'}
目标岗位关键词：{_brief(kw_all)}
目标区域：{_brief(region_all) or '不限'}
目标行业：{_brief(ind_all) or '不限'}

以下是实时检索材料（引用 [检索i.j] 编号）：
{context}
{links_block}
{profile_section}{filter_note}{precise_note}{count_note}{signals_block}请基于材料输出「今日机会池」，**全部用表格呈现，禁止大段散文**：

## 表一 · 机会池总表（必须放最前面）
| 级 | 岗位 | 公司 | 地区 | 公司性质 | 公司规模 | 薪资 | 福利保障 | 经验/学历要求 | 发布时间 | 来源平台 | 链接 | 风险标记 | JD 要点 |
- 级：高 / 中 / 低；命中底线写「高⚠️底线」，疑似刷量写「中⚠️刷量」，行业不符写「低（行业不符）」
- 风险标记（必填）：命中公司风险关键词就写关键词（如「失信」「欠薪」「被执行」「投诉」）；命中一票否决级风险写「⚠️一票否决：<关键词>」，同时把「级」降为「低⚠️公司风险」
- 字段材料没有的写「材料未见」；JD 要点取自【网页正文】，标注 [网页k]
- 链接：优先填表六编号 [n]；材料无 url 时用上方平台直达链接

## 表二 · 加权评分总览
| 公司/机会 | 体系成熟度(25) | 发挥成长(20) | 稳定性(15) | 渠道健康(10) | 体量匹配(10) | 薪资(10) | 团队(5) | WLB(5) | 加权总分 | 分层 | 命中底线 | 关键依据 |
分层：≥80 优先投递；60–79 谨慎；<60 直接排除；命中任一底线直接排除。材料覆盖不到的维度给低分并注明「待核实：去哪查/问谁」。
命中公司风险关键词（尤其一票否决级）的机会，分层最高只能到「谨慎」，并在关键依据里写明命中的关键词。

## 表三 · 逐条深度解析（高/中推荐每条都要有）
| 公司/机会 | 业务与行业地位 | 对你的价值（能否放大 5000 万级） | 风险点（体系/回款/压货/空壳/失信/欠薪） | 面试必问 3 题 | 谈薪要点 | 公开联系方式 |

## 表四 · 风险 · 刷量 · 口碑 综合判定
| 公司/机会 | 公司风险（命中关键词 + 结论：真实招聘可能性高 / 需核实 / 高风险） | 刷量/虚假招聘（多平台重复、长期挂出、批量发布、猎头代招） | 雇主口碑（看准/脉脉/知乎/投诉平台的评价与高频负面主题） | 依据（关键词、重复次数、时间跨度、JD 是否空洞） | 建议核实动作 |

## 表五 · 扩张利好与政策/产业匹配
| 公司 | 重大利好（融资/上市/并购/扩产/技术突破/中标） | 时间 | 依据 | 对招聘规模的影响（是否真在扩人） | 政策与产业匹配（国家/地方规划、扶持目录） | 上下游机会 |
- 利好必须来自材料；没有就写「材料未见」——不得凭公司名气推断扩张
- 政策匹配写清「哪份文件、哪一级、支持什么」；查不到写「材料未见（去哪查：发改委/工信部/省政府官网规划专栏）」

## 表六 · 来源与检索命中清单
| 编号 | 标题 | 平台 | 链接 | 是否含 JD 正文 | 备注 |
链接必须从检索材料原样复制，绝不编造、不改写；材料无 url 写「引擎未返回链接」并改用平台直达链接。

规则：① 只输出表格，表格外最多一行说明；② 联系方式严守合规——只引用材料中**已公开招聘**的联系人称呼/邮箱/总机，**禁止任何个人手机号与推断号码**，没有就写「材料未公开」；③ 若材料只有公司/行业级信息、没有具体在招岗位：先在表一前用一行粗体写「本次检索未覆盖具体岗位」，再按公司填表并给站内检索指引；④ 不编造材料之外的在招信息；⑤ 铁律：不臆测、不补全，缺什么写什么。"""

    r = await _llm_call(provider, [
        {"role": "system", "content": RADAR_SYSTEM},
        {"role": "user", "content": re.sub(r"\n{3,}", "\n\n", user)},
    ])
    if not r.get("ok"):
        return r
    body = r["content"]
    rows = _extract_pool_rows(body)
    _attach_scores(rows, _extract_score_map(body))
    seen_keys = [f"{x.get('公司', '')}·{x.get('岗位', '')}" for x in rows]
    return {
        "ok": True,
        "content": disclaimer + body,
        "model": provider.model,
        "signals": sig,
        "diagnostics": diag,
        "pool": {
            "rows": len(rows),
            "want": want,
            "batch": int(req.batch or 0),
            "paths": len(queries),
            "per_query": per_query,
            "seen": seen_keys,
            "keys": [{"post": x.get("岗位", ""), "company": x.get("公司", "")} for x in rows],
            "items": rows,   # 前端「机会池面板」用它渲染卡片/紧凑表格
        },
    }


# ---------- 直连编排：行业赛道研判（生命周期五档） ----------

INDUSTRY_SYSTEM = (
    "你是一位产业研究 + 一级市场投资的赛道分析师，同时懂中国渠道与销售岗位的用工现实。"
    "你的任务不是夸行业，而是判断「这个行业现在处在生命周期的哪一档，以及候选人现在进去划不划算」。"
    "所有输出使用中文 Markdown，全部用表格；只依据提供的检索材料与本地规则层结论写作，"
    "不得编造数字、政策文件名或企业事件；材料未覆盖的写「材料未见」并给出核实路径。"
    "**本地规则层给出的档位与分数不得被推翻**（它由可复算的加权规则得出），你只负责解释、补充与给动作。"
)

INDUSTRY_SECTIONS = """一、赛道判定（档位 + 分数 + 一句话结论 + 与检索材料特征词的交叉验证）
二、需求与增速（规模、增速、增长来源、替代威胁；每条标数据来源或「材料未见」）
三、竞争格局与集中度（龙头、玩家数量变化、价格战与毛利、渠道/终端结构）
四、政策与产业链（国家/地方规划、扶持或限制、上下游机会与风险）
五、进入时机与个人动作建议（结合候选人画像：投递优先级 / 该选什么岗 / 谈薪与避坑 / 3 个必须先核实的信号）"""


class DirectIndustryRequest(BaseModel):
    provider_id: str
    industry: str
    region: str = "河南"
    profile: str = ""
    facts: dict[str, Any] = {}
    manual_material: str = ""   # 手工粘贴的材料：填了就直接跳过搜索引擎


def _industry_block(res: dict[str, Any], scan: dict[str, Any]) -> str:
    """把规则层档位与词库交叉验证整理成提示词块。"""
    st = res["stage"]
    lines = [
        "\n【本地规则层赛道判定（确定性加权计算，同输入同输出）】",
        f"- 行业：{res['industry']}{('（' + res['region'] + '）') if res.get('region') else ''}"
        f" ｜ 分数 {res['score']}/100 ｜ 档位：**{st['name']}** ｜ 置信度 {int(res['confidence'] * 100)}%",
        f"- 该档特征：{st['features']}",
        f"- 该档机会：{st['opportunity']}",
        f"- 该档风险：{st['risk']}",
        f"- 进入结论：**{st['entry_verdict']}**；岗位建议：{st['job_advice']}",
    ]
    if res["positive"]:
        lines.append("- 支撑因素：" + "、".join(res["positive"]))
    if res["negative"]:
        lines.append("- 拖累因素：" + "、".join(res["negative"]))
    if res["caps"]:
        lines.append("- 硬性上限触发：" + "；".join(res["caps"]))
    if res["missing"]:
        lines.append("- 缺失关键字段（置信度受限，须在报告中标注待核实）：" + "、".join(res["missing"]))
    if scan.get("dominant"):
        dc = scan["counts"]
        av = scan.get("avg") or {}
        dominated = next((s["name"] for s in STAGES if s["id"] == scan["dominant"]), scan["dominant"])
        lines.append(
            "- 检索材料阶段特征词（已剔除检索式回显、按键词数归一）："
            + "、".join(f"{k} {v}" for k, v in dc.items() if v)
            + f" → 每词均值最高的是「{dominated}」"
            + ("（均值：" + "、".join(f"{k} {v}" for k, v in av.items()) + "）" if av else "")
        )
        top = [h for h in scan.get("hits", [])][:6]
        if top:
            lines.append("  · 高频词：" + "、".join(f"{h['keyword']}×{h['count']}" for h in top))
        lines.append(
            "  · 提醒：词频只反映「材料怎么说」，媒体语言天然偏负面（价格战/内卷易被提及），"
            "不能据此推翻规则层档位；请结合需求、毛利、产能等事实判断。"
        )
    lines.append(
        "【使用要求】\n"
        "① 第一节必须原样给出规则层档位与分数，并说明检索材料是印证还是冲突；冲突时以规则层档位为准，"
        "同时指出「补哪个字段可以修正判定」；\n"
        "② 第二、三节的数字必须来自材料并标注来源；查不到就写「材料未见（去哪查：国家统计局/行业协会/券商研报/上市公司年报）」；\n"
        "③ 第四节必须写清「哪份文件、哪一级、支持或限制什么」；\n"
        "④ 第五节要落到具体动作：哪些行业细分优先投、该选什么岗位、谈薪要点、避坑清单、先核实哪 3 件事。\n"
    )
    return "\n".join(lines) + "\n"


@router.post("/ai/direct/industry")
async def direct_industry(req: DirectIndustryRequest):
    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        return {"ok": False, "error": "模型不存在或已被删除，请重新选择。"}
    industry = req.industry.strip()
    if not industry:
        return {"ok": False, "error": "请先填写行业名称。"}
    region = (req.region or "河南").strip()

    search_cfg = _load_search()
    context = ""
    prefix = ""
    queries: list[str] = []
    diag: dict[str, Any] = {"engine": search_cfg.engine, "errors": []}
    manual = (req.manual_material or "").strip()
    if manual:
        context = build_manual_context(manual)
        diag = {"engine": "manual", "paths": 0, "results": 0, "manual_chars": len(manual),
                "errors": [], "hint": "本次使用手工粘贴材料，未调用搜索引擎"}
        prefix = f"> 📋 本次研判基于**你手工粘贴的材料**（{len(manual)} 字）+ 本地规则层，未调用搜索引擎。\n\n"
    elif search_cfg.engine != "none" and search_cfg.api_key:
        queries = industry_queries(industry, region)
        context, _notes, diag = await _gather_search(search_cfg, queries)
        if not context.strip() and diag.get("errors"):
            # 行业研判的规则层不依赖联网，所以这里**不直接失败**：给出诊断 + 用规则层结论继续
            prefix = (
                "> ⚠️ **联网检索失败，本报告只有本地规则层结论**（需求量/政策/竞争格局等检索内容缺失）。\n"
                f"> **检索诊断**：{diag_error_text(diag)}\n\n"
            )
        elif not context.strip():
            prefix = (
                f"> ⚠️ 联网检索无结果（{diag.get('paths')} 路全部为空），"
                "本报告只有本地规则层结论，请谨慎核对。\n\n"
            )
    else:
        prefix = "> ⚠️ 未启用联网搜索（设置 → 模型直连 → 搜索引擎），以下内容基于模型既有知识与本地规则层生成，请谨慎核对。\n\n"

    # 规则层 + 词库层
    res = industry_evaluate({"industry": industry, "region": region, **(req.facts or {})})
    scan = scan_stage(context)
    block = _industry_block(res, scan)

    profile_txt = req.profile.strip()
    profile_section = (
        f"\n【候选人画像（判断「你这个阶段该不该进」的依据）】\n{profile_txt}\n"
        "第五节必须结合画像给结论：候选人是「成熟体系放大器」（擅长在成熟体系里放大操盘规模），"
        "因此蓝海朝阳/平稳存量最优、龙头优先；新势力要按风投标准核实现金与融资节奏；"
        "红海必须核实提成兑现与账期；夕阳原则上不进并给迁移路径。\n"
        if profile_txt else ""
    )

    user = f"""请对行业「{industry}」做赛道研判（区域视角：{region}）。

{block}
{('以下是实时检索材料，引用 [检索i.j] 编号：' if context else '')}
{context}

【输出要求】固定五节，全部用表格（表格外每节最多两行说明）：
{INDUSTRY_SECTIONS}
{profile_section}{('先说明：' + prefix.strip() + chr(10)) if prefix else ''}"""
    user = re.sub(r"\n{3,}", "\n\n", user)

    r = await _llm_call(provider, [
        {"role": "system", "content": INDUSTRY_SYSTEM},
        {"role": "user", "content": user},
    ])
    if not r.get("ok"):
        return r
    content = _prepend_prefix(prefix, r["content"])

    meta = {
        "model": provider.model,
        "kind_note": "行业赛道研判",
        "stage": res["stage"]["name"],
        "stage_score": res["score"],
        "region": region,
    }
    archived = {}
    try:
        archived = save_report(industry, content, kind="行业赛道研判", meta=meta,
                              facts=(req.facts or None), root="knowledge/_行业")
    except Exception as e:
        archived = {"ok": False, "error": f"存档失败：{e}"}

    return {
        "ok": True,
        "content": content,
        "model": provider.model,
        "industry": res,
        "stage_scan": scan,
        "paths": len(queries),
        "diagnostics": diag,
        "archive": archived,
    }


# ---------- 直连编排：深度分析（投资视角 VC 五步 / 优秀企业筛选 6 步） ----------

DEEP_SYSTEM = {
    "invest": (
        "你是资深猎头 + 企业尽调专家 + 风险投资分析师三位一体。"
        "前提：求职 = 一笔重仓风险投资——候选人投入的是每天 8 小时+ 的黄金年华，"
        "公司给的是「现金 + 成长权」，所以用投资人选股逻辑评估雇主。"
        "只依据下方候选人画像与检索材料分析；公开材料查不到的数据不要编造，"
        "统一写「待验证」并给出查证路径（去哪查 / 问谁）；不臆造候选人经历。"
        "全程中文 Markdown，输出像 VC 投委会报告一样结构清晰。"
    ),
    "screen": (
        "你是深耕家电/厨电/耐用消费品行业 15 年以上的资深猎头 + 渠道营销专家 + 企业尽调顾问。"
        "候选人定位：成熟体系放大器——在成熟严谨体系下可操盘 5000 万级盘子，擅长快速复制放大；"
        "而非乱局从零硬建（虽有 0→1 经验）。"
        "只依据下方候选人画像与检索材料分析；查不到的信息写「待核实」并给验证方法；"
        "不臆造候选人经历与企业实况。全程中文 Markdown，结论具体可执行。"
    ),
}


def _invest_user(profile: str, material: str) -> str:
    return f"""候选人画像与风险偏好（务必遵守，勿改动）：
{profile.strip() or '（未提供）'}

本次岗位雷达检索到的机会池 / 候选材料（据此分析，不要编造材料之外的在招信息）：
{material.strip()}

请按「风险投资人选股逻辑」执行以下 5 步分析：

# 1 赛道判断（顺势而为 + 时光机）
按投资价值排序：河南家电/厨电/耐用消费品中「一二线已验证、正在河南/县域加速复制」的细分品类，给出势能依据。

# 2 潜力企业清单（80/20 仓位）
- 主力 80%（A/B 轮型）：成熟体系 + 扩张期——品牌方 / 一级代理 / 大型经销商集团，含上市公司第二曲线；
- 机会 20%（天使轮型）：有产业背景创始人、正在规范化的本地潜力品牌。
每家标注：为什么像潜力股、核心增长信号、主要风险。

# 3 风投式五张尽调卡
对候选公司输出：① 市场：该品类河南盘子多大、候选人能操盘多少；② 增长验证：近两年营收/门店/代理商数增长（注明数据源或验证路径）；③ 团队：老板/直属上级是否「对的人」（诚信、产业背景、带人记录）及如何查证；④ 单位经济模型：经销商单店盈利、返利/账期健康度；⑤ 现金流：结算及时性、有无拖欠红线。

# 4 逆向否决 + 价值判断
先用画像中的底线清单做减法（命中即直接排除），再用巴菲特标准回答：这家公司值得候选人用 3–5 年「买入持有」吗？为什么？

# 5 决策输出
输出「重仓买入（优先投递）/ 观察仓（跟踪）/ 直接卖出（排除）」三层名单；每家给：投递路径（海投/内推/定向私信）+ 需验证的 3 个关键信号 + 查证方法。

材料不足的维度统一标注「待验证」并给查证动作，不要编造数字。"""


def _screen_user(profile: str, material: str) -> str:
    return f"""候选人画像与匹配标准（务必遵守，勿改动）：
{profile.strip() or '（未提供）'}

本次岗位雷达检索到的候选材料（据此筛选，不要编造材料之外的企业信息）：
{material.strip()}

请按以下 6 步执行「优秀企业筛选与匹配」：

第 1 步【画像校准】：用 3 句话复述对候选人的理解，点明他是「成熟体系放大器」型操盘手，
最该匹配「已有相对完整体系、需要有人放大」的企业，最该避开「体系残缺、指望他一人从零硬撑」的坑。

第 2 步【目标企业画像】：定义最适合他的企业长什么样：企业类型（品牌方 / 一级代理 / 大型经销商集团 / 平台型）、
业务模式（守成维稳 vs 攻坚开荒）、体系成熟度（渠道政策 / 终端管理 / 财务结算 / 培训体系是否已有）。

第 3 步【筛选维度与验证方法】：按 8 个维度给出可执行评估清单，每维给「去哪查、问谁、看什么信号」：
1 体系成熟度（最关键）；2 渠道基本面（返利/结算是否及时）；3 业绩考核（压库存冲量还是健康动销）；
4 区域市场现状（空白待开发 vs 维稳提效）；5 发展空间（能否升省区/渠道总监）；
6 稳定性（管理层/是否频繁换区域负责人）；7 待遇真实性（薪资构成/提成占比/五险一金基数）；
8 操盘体量匹配（3000 万–1 亿级承接 5000 万能力；<1000 万视为浪费、降分）。

第 4 步【匹配打分模型】：用 0-100 分制按画像权重打分并输出 Markdown 表：
| 维度 | 权重 | 得分(0-100) | 加权分 | 点评 |
权重默认：体系成熟度 25% / 发挥成长空间 20% / 稳定性 15% / 渠道健康度 10% / 操盘体量 10% / 薪资待遇 10% / 团队管理层 5% / 工作生活平衡 5%（以画像给出的为准）。
给出每维高/低分标准；命中画像底线任一条的维度给 0 分并在点评注明。

第 5 步【避坑清单】：给出面试/背调必须查证的红色信号清单（含如何判断「公司体系到底成不成熟」），
每条配一句不冒犯的反问话术（例如如何委婉问出「上一个区域经理为什么走」）。

第 6 步【决策建议】：按「优先投递 / 谨慎考虑 / 直接排除」分层；
说明哪类企业最可能把他的「成熟体系放大」能力价值最大化。"""


DEEP_TITLES = {
    "invest": "投资视角 · 潜力企业深挖",
    "screen": "优秀企业筛选（6 步）",
}


@router.post("/ai/direct/deep")
async def direct_deep(req: DirectDeepRequest):
    mode = req.mode
    if mode not in DEEP_SYSTEM:
        return {"ok": False, "error": "未知分析模式，请用 invest 或 screen。"}
    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        return {"ok": False, "error": "模型不存在或已被删除，请重新选择。"}
    if not req.radar_result.strip():
        return {"ok": False, "error": "请先运行岗位雷达生成机会池，再执行深度分析。"}
    user = _invest_user(req.profile, req.radar_result) if mode == "invest" else _screen_user(req.profile, req.radar_result)
    r = await _llm_call(provider, [
        {"role": "system", "content": DEEP_SYSTEM[mode]},
        {"role": "user", "content": re.sub(r"\n{3,}", "\n\n", user)},
    ])
    if not r.get("ok"):
        return r
    return {"ok": True, "content": r["content"], "model": provider.model, "mode": mode, "title": DEEP_TITLES[mode]}


# ---------- 直连编排：目标企业触点地图（公开渠道联系人与触达路径） ----------

CONTACT_FILE = DATA_DIR / "contact.json"


class ContactConfig(BaseModel):
    qcc_api_key: str = ""   # 企查查开放平台（预留，填 Key 后可接入付费工商数据）
    tyc_api_key: str = ""   # 天眼查开放平台（预留）


class ContactMapRequest(BaseModel):
    provider_id: str
    company_name: str
    profile: str = ""       # 候选人画像（用于生成触达策略）


def _load_contact_cfg() -> ContactConfig:
    if not CONTACT_FILE.exists():
        return ContactConfig()
    try:
        return ContactConfig(**json.loads(CONTACT_FILE.read_text("utf-8")))
    except Exception:
        return ContactConfig()


async def _paid_company_lookup(company: str) -> tuple[str, str]:
    """付费工商数据源预留位（企查查 / 天眼查）。
    未配置 Key → 返回空，不影响免费检索链路；
    配置 Key 后在此接入开放平台，把工商登记信息（法定代表人/主要人员/注册电话/邮箱）格式化为文本返回。
    """
    cfg = _load_contact_cfg()
    if not (cfg.qcc_api_key or cfg.tyc_api_key):
        return "", ""
    return "", "（已配置付费数据源 Key，但企业信息接口尚未接入——待实现）"


CONTACT_SYSTEM = (
    "你是企业情报与商务触达顾问，擅长从公开信息中整理「合规可用的联系人入口」。"
    "合规红线（必须遵守）："
    "① 只输出公开渠道可查的信息：企业工商登记公开信息、上市公司法定披露（年报/公告中的董秘/证券事务代表）、"
    "企业官网公开招聘与商务联系方式、招标/中标公告中的项目联系人、领英/脉脉公开职业档案中的姓名与职务；"
    "② **严禁输出任何个人手机号**，严禁推断、拼接、猜测号码；"
    "③ 每条信息标注来源（[检索i.j]/[网页k]）与性质（公开检索 / 法定披露 / 需自行核实）；"
    "④ 查不到就写「未查到」并给查证路径，不得编造。"
    "输出中文 Markdown，固定七节结构，不要多余客套。"
)


@router.post("/ai/direct/contact-map")
async def direct_contact_map(req: ContactMapRequest):
    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        return {"ok": False, "error": "模型不存在或已被删除，请重新选择。"}
    company = req.company_name.strip()
    if not company:
        return {"ok": False, "error": "请输入公司名称。"}

    search_cfg = _load_search()
    queries: list[str] = []
    if search_cfg.engine != "none" and search_cfg.api_key:
        queries = [
            f"{company} 工商信息 法定代表人 主要人员 注册电话",
            f"{company} 官网 联系我们 招聘 邮箱 电话",
            f"{company} 年报 董秘 证券事务代表 联系电话 邮箱",
            f"{company} 河南 分公司 办事处 联系电话",
            f"{company} 河南 招标 中标 公告 联系人",
            f"{company} linkedin 大区经理 渠道总监",
        ]

    context = ""
    engine_errs: list[str] = []
    if queries:
        context, _notes, diag = await _gather_search(search_cfg, queries, scope="all")
        if not context.strip() and diag.get("errors"):
            return {
                "ok": False,
                "error": "联网检索失败，无法整理触点地图：" + diag_error_text(diag),
                "diagnostics": diag,
                "suggestion": "到「设置 → 搜索引擎」检查额度/Key，或换引擎后重试。",
            }

    paid_text, paid_note = await _paid_company_lookup(company)

    if not context.strip():
        prefix = (
            f"> ⚠️ 未启用联网搜索或检索无结果，无法整理「{company}」的公开触点。"
            "启用方法：设置 → 模型直连 → 搜索引擎（Tavily / 智谱 / Serper / Brave / 博查）填 Key → 保存。\n"
            + (f"\n> **检索诊断**：{diag_error_text(diag)}\n" if diag.get("errors") else "")
            + "\n"
        )
    else:
        prefix = ""

    user = f"""目标公司：{company}
候选人画像（用于生成触达策略）：{req.profile.strip() or '（未提供）'}

以下是公开检索材料（引用 [检索i.j] / [网页k] 编号）：
{context}
{paid_text}

请输出「目标企业触点地图」，固定七节：

## 一、企业公开信息
法定代表人 / 主要人员 / 注册资本 / 成立时间 / 河南分支机构与办事处（每条标来源；查不到写「未查到」）

## 二、公开招聘入口
官网招聘页、招聘邮箱、HR 专线（**仅材料中已公开招聘的信息**）

## 三、上市公司法定披露
董秘 / 证券事务代表：姓名 + 电话 + 邮箱（来源：年报/公告）；若非上市公司或未查到，写「非上市 / 未查到」

## 四、关键人路径（只给公开职业档案中的姓名与职务，不给私人联系方式）
领英/脉脉公开主页、行业协会、展会名录等；给核查路径

## 五、项目与商务触点
河南地区招标/中标公告联系人、招商加盟热线、区域办事处电话、B2B 平台公开联系人

## 六、触达策略（结合候选人画像）
按「先探体系 → 再找对人 → 再谈岗位/合作」给 3–5 步，每步配一句开场话术

## 七、合规与核实说明
逐条标注来源与性质（公开检索 / 法定披露 / 需自行核实）；明确说明：**个人手机号不予提供**，
如需商务联系请走公开总机、官方邮箱或领英沟通。

硬性要求：**全文不得出现任何个人手机号**；不推断、不拼接号码；材料未覆盖的写「未查到 + 去哪查」。"""
    r = await _llm_call(provider, [
        {"role": "system", "content": CONTACT_SYSTEM},
        {"role": "user", "content": re.sub(r"\n{3,}", "\n\n", user)},
    ])
    if not r.get("ok"):
        return r
    return {"ok": True, "content": prefix + r["content"], "model": provider.model, "paid_note": paid_note}


# ---------- 直连编排：模拟面试（P1 文字版：多轮出题 + 即时点评 + 复盘报告） ----------

INTERVIEW_PERSONAS = {
    "hr": "HR（温和、流程化，关注匹配度、稳定性与离职原因）",
    "region_director": "直属大区总（业务犀利，紧盯数据、你的具体动作与结果）",
    "boss": "总经理/老板（关注格局、风险、体系成熟度与投入产出）",
    "stress": "压力面面试官（语气质疑、连续追问、刻意制造紧张感）",
}

# 面试阶段计划：阶段 → 题量
INTERVIEW_PLAN: list[tuple[str, int]] = [
    ("intro", 1),
    ("resume", 4),
    ("professional", 4),
    ("pressure", 2),
    ("ask", 1),
]

INTERVIEW_STAGE_LABELS = {
    "intro": "开场与自我介绍",
    "resume": "履历深挖（STAR 追问）",
    "professional": "专业题（渠道/经销商/回款/库存/单店模型）",
    "pressure": "压力与动机",
    "ask": "你的反问环节",
    "done": "面试结束",
}


class InterviewTurnRequest(BaseModel):
    provider_id: str
    stage: str = "intro"
    round_no: int = 1
    history: list[ChatMessage] = []
    profile: str = ""
    jd: str = ""
    company: str = ""
    role_persona: str = "hr"
    user_answer: str = ""


class InterviewReviewRequest(BaseModel):
    provider_id: str
    history: list[ChatMessage] = []
    profile: str = ""
    jd: str = ""
    company: str = ""
    role_persona: str = "hr"


def _interview_advance(stage: str, round_no: int) -> tuple[str, int]:
    """按题量计划推进到下一题；返回 (阶段, 题号)。超出计划 → ('done', 0)。"""
    order = [s for s, _ in INTERVIEW_PLAN]
    counts = dict(INTERVIEW_PLAN)
    if stage not in counts:
        return "done", 0
    if round_no < counts[stage]:
        return stage, round_no + 1
    idx = order.index(stage)
    if idx + 1 < len(order):
        return order[idx + 1], 1
    return "done", 0


def _interview_system(req: InterviewTurnRequest) -> str:
    persona = INTERVIEW_PERSONAS.get(req.role_persona, INTERVIEW_PERSONAS["hr"])
    stage_label = INTERVIEW_STAGE_LABELS.get(req.stage, req.stage)
    return (
        f"你是【{persona}】，正在面试一位应聘「{req.company or '目标公司'}」"
        f"「{req.jd[:60] or '区域/渠道管理岗'}」的候选人。\n"
        "【候选人画像（据此提问，禁止重复问画像里已有的信息）】\n"
        f"{req.profile.strip() or '（未提供）'}\n"
        "【面试规则】\n"
        "1. 一次只问一个问题，口语化、简短（≤60 字），像真实面试。\n"
        "2. 追问遵循 STAR：回答里缺数据、缺「你的具体动作」、缺结果时，必须追问其中一项。\n"
        "3. 语气严格符合你的角色设定；不要客套长篇，不要替候选人编造经历。\n"
        "4. 每轮先给≤3 句即时点评（亮点 / 缺失 / 建议），再给下一题；输出用如下两段式：\n"
        "【点评】…（第一题没有候选人回答时可省略这一段）\n"
        "【提问】…\n"
        "5. 不要透露这是模拟；不要输出题目编号以外的解释。\n"
        f"6. 当前进度：{stage_label}（第 {req.round_no} 题）。"
    )


@router.post("/ai/interview")
async def interview_turn(req: InterviewTurnRequest):
    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        return {"ok": False, "error": "模型不存在或已被删除，请重新选择。"}

    stage = req.stage if req.stage in INTERVIEW_STAGE_LABELS else "intro"
    round_no = max(1, req.round_no or 1)
    answer = req.user_answer.strip()
    finished = False
    if answer:
        next_stage, next_round = _interview_advance(stage, round_no)
        finished = next_stage == "done"
    else:
        next_stage, next_round = stage, round_no

    if finished:
        ask_line = "候选人的反问环节已结束，请给一句自然的收尾（告知后续流程），不要再提问。"
    else:
        ask_line = (
            f"请提出【{INTERVIEW_STAGE_LABELS.get(next_stage, next_stage)}】的第 {next_round} 题。"
        )

    if answer:
        user = (
            f"候选人刚才的回答：\n{answer}\n\n"
            "请先给≤3 句即时点评（以【点评】开头），然后"
            + ("自然收尾、不要再提问。" if finished else f"提出下一题（以【提问】开头）。{ask_line}")
        )
    else:
        user = f"请开始/继续面试：{ask_line}"

    messages = [{"role": "system", "content": _interview_system(req)}]
    messages += [m.model_dump() for m in req.history][-20:]
    messages.append({"role": "user", "content": user})

    r = await _llm_call(provider, messages)
    if not r.get("ok"):
        return r
    return {
        "ok": True,
        "reply": r["content"],
        "stage": next_stage,
        "round_no": next_round,
        "finished": finished,
        "stage_label": INTERVIEW_STAGE_LABELS.get(next_stage, next_stage),
        "progress": _interview_progress(stage, round_no),
        "model": provider.model,
    }


def _interview_progress(stage: str, round_no: int) -> str:
    """第 N / 总题数。"""
    total = sum(c for _, c in INTERVIEW_PLAN)
    done = 0
    for s, c in INTERVIEW_PLAN:
        if s == stage:
            done += min(round_no, c)
            break
        done += c
    return f"{min(done, total)} / {total}"


INTERVIEW_REVIEW_SYSTEM = (
    "你是面试教练，负责为候选人做面试复盘。"
    "只依据提供的面试记录点评，不要编造候选人没说过的内容；"
    "所有输出使用中文 Markdown，**全部用表格**，表格外最多一行说明。"
)


@router.post("/ai/interview/review")
async def interview_review(req: InterviewReviewRequest):
    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        return {"ok": False, "error": "模型不存在或已被删除，请重新选择。"}
    if not req.history:
        return {"ok": False, "error": "没有面试记录，无法生成复盘。"}

    transcript_lines: list[str] = []
    for m in req.history:
        who = "面试官" if m.role == "assistant" else "候选人"
        transcript_lines.append(f"【{who}】{m.content}")
    transcript = "\n".join(transcript_lines)[-12000:]

    persona = INTERVIEW_PERSONAS.get(req.role_persona, INTERVIEW_PERSONAS["hr"])
    user = f"""面试官角色：{persona}
目标公司：{req.company or '（未指定）'}
岗位 JD（节选）：{req.jd[:800] or '（未提供）'}

候选人画像：
{req.profile.strip() or '（未提供）'}

面试记录（按时间顺序）：
{transcript}

请输出《面试复盘报告》，**全部用表格**：

## 表一 · 总评
| 总分(0-100) | 等级 | 一句话结论 | 是否建议进入下一轮 | 最大亮点 | 最大短板 |

## 表二 · 逐题评分
| 题号 | 面试官问题（简写） | 你的回答要点 | 内容完整(0-5) | STAR结构(0-5) | 数据支撑(0-5) | 表达条理(0-5) | 主要问题 |

## 表三 · 更好的答法
| 题号 | 你的原话（节选） | 改写示范 | 为什么更好 |

## 表四 · 风险暴露
| 风险点 | 出现在的题目 | 面试官可能的疑虑 | 补救话术 |

## 表五 · 训练清单
| 优先级 | 要补强的地方 | 具体动作 | 练习素材/题目 |

要求：逐题评分必须覆盖面试记录里的每一道题；没有的信息写「记录中未涉及」，不要臆造。"""

    r = await _llm_call(provider, [
        {"role": "system", "content": INTERVIEW_REVIEW_SYSTEM},
        {"role": "user", "content": user},
    ])
    if not r.get("ok"):
        return r
    return {"ok": True, "content": r["content"], "model": provider.model}


# ---------- 工具调用（MCP）：让模型按需调用外部成熟模块 ----------

class ChatToolsRequest(BaseModel):
    provider_id: str
    messages: list[ChatMessage] = []
    server_ids: list[str] = []          # 空 = 所有已启用的 MCP 服务器
    max_rounds: int = 3
    system: str = ""


@router.post("/ai/chat-tools")
async def ai_chat_tools(req: ChatToolsRequest):
    """带工具调用的对话：模型可自行调用 MCP 工具（最多 max_rounds 轮），并返回调用轨迹便于审计。"""
    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        return {"ok": False, "error": "模型不存在或已被删除，请重新选择。"}

    try:
        from app.mcp_host import aggregate_tools, call_tool_direct
    except Exception as e:
        return {"ok": False, "error": f"MCP 模块不可用：{e}"}

    msgs: list[dict] = []
    if req.system.strip():
        msgs.append({"role": "system", "content": req.system.strip()})
    msgs += [m.model_dump() for m in req.messages]

    tools, tool_errors = await aggregate_tools(req.server_ids or None)
    trace: list[dict] = []

    if not tools:  # 没有可用工具 → 退化为普通对话
        r = await _llm_call(provider, msgs)
        return {
            "ok": r.get("ok", False),
            "content": r.get("content", ""),
            "error": r.get("error"),
            "trace": trace,
            "tool_errors": tool_errors,
            "model": provider.model,
        }

    schema = [{k: v for k, v in t.items() if k != "_mcp"} for t in tools]
    by_name = {t["function"]["name"]: t["_mcp"] for t in tools}
    rounds = max(1, min(5, req.max_rounds or 3))

    for _ in range(rounds):
        r = await _llm_call_tools(provider, msgs, schema)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error"), "trace": trace, "tool_errors": tool_errors}
        msg = r["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return {
                "ok": True,
                "content": msg.get("content") or "",
                "trace": trace,
                "tool_errors": tool_errors,
                "model": provider.model,
            }
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            fn = c.get("function") or {}
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            meta = by_name.get(name)
            if not meta:
                result = f"未知工具：{name}"
            else:
                res = await call_tool_direct(meta["server_id"], meta["tool"], args)
                result = res.get("content", "") if res.get("ok") else f"调用失败：{res.get('error')}"
            trace.append(
                {
                    "tool": name,
                    "server_id": (meta or {}).get("server_id", ""),
                    "arguments": args,
                    "ok": not str(result).startswith("调用失败"),
                    "result_preview": str(result)[:600],
                }
            )
            msgs.append({"role": "tool", "tool_call_id": c.get("id") or name, "content": str(result)[:8000]})

    return {"ok": False, "error": f"工具调用超过 {rounds} 轮仍未结束", "trace": trace, "tool_errors": tool_errors}
