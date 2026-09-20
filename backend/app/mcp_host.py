"""MCP 扩展：把成熟的 MCP 服务器接进项目，按需调用其工具。

配置：data/config/mcp.json
- stdio：后端按配置的 command/args 拉起子进程（默认 npx / uvx），首次运行会联网下载包
- http ：连接你已运行的 streamable-http 服务

实现取舍：一次调用一个会话（拉起 → initialize → 调用 → 关闭）。比长连接简单可靠，
便于"用完即走"；工具清单单独缓存，避免每次刷新都拉起进程。

安全：默认不自动批准；高风险工具（写文件、执行命令等）由前端逐次确认后调用。
"""
import asyncio
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/mcp")
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "config"
CONFIG_FILE = DATA_DIR / "mcp.json"

# 工具清单缓存：server_id -> (时间戳, tools)
_tools_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
CACHE_TTL = 300  # 秒


class McpServer(BaseModel):
    id: str = ""
    name: str = ""
    transport: str = "stdio"          # stdio | http
    command: str = "npx"
    args: list[str] = []
    env: dict[str, str] = {}
    url: str = ""
    enabled: bool = True
    auto_approve: bool = False        # 免确认（高风险工具建议保持 False）
    note: str = ""


class McpConfig(BaseModel):
    servers: list[McpServer] = []


class McpCallRequest(BaseModel):
    server_id: str
    tool: str
    arguments: dict[str, Any] = {}


def _load() -> McpConfig:
    if not CONFIG_FILE.exists():
        return McpConfig()
    try:
        return McpConfig(**json.loads(CONFIG_FILE.read_text("utf-8")))
    except Exception:
        return McpConfig()


def _save(cfg: McpConfig) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(cfg.model_dump_json(indent=2), "utf-8")


def _server(sid: str) -> McpServer:
    for s in _load().servers:
        if s.id == sid:
            return s
    raise HTTPException(status_code=404, detail=f"未找到 MCP 服务器：{sid}")


def _resolve_command(cmd: str) -> str:
    """Windows 上 npx/uvx 实际是 .cmd，CreateProcess 不会自动补扩展名 → 这里解析成绝对路径。"""
    if not cmd:
        return cmd
    if os.path.isabs(cmd) and os.path.exists(cmd):
        return cmd
    if os.name == "nt" and not os.path.splitext(cmd)[1]:
        for ext in (".cmd", ".exe", ".bat"):
            found = shutil.which(cmd + ext)
            if found:
                return found
    return shutil.which(cmd) or cmd


class StdioRpc:
    """极简 MCP stdio 客户端：newline-delimited JSON-RPC 2.0。

    刻意不用任何 asyncio 子进程：受限环境（沙箱/某些服务账户）会拒绝 asyncio 的
    子进程创建，而普通 Popen + 线程读写到处都能跑；实现也更少黑盒。
    """

    def __init__(self, command: str, args: list[str], env: dict[str, str]):
        self.proc = subprocess.Popen(  # noqa: S603
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )
        self._lock = threading.Lock()
        self._pending: dict[int, dict[str, Any]] = {}
        self._errors: queue.Queue[str] = queue.Queue()
        self._id = 0
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8", "ignore"))
            except Exception:
                continue
            if isinstance(msg, dict) and "id" in msg:
                self._pending[int(msg["id"])] = msg

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for raw in self.proc.stderr:
            text = raw.decode("utf-8", "ignore").strip()
            if text:
                self._errors.put(text)

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 60) -> dict[str, Any]:
        with self._lock:
            self._id += 1
            rid = self._id
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if rid in self._pending:
                return self._pending.pop(rid)
            if self.proc.poll() is not None:
                errs = []
                while not self._errors.empty():
                    errs.append(self._errors.get())
                raise RuntimeError(
                    f"MCP 进程已退出（code={self.proc.returncode}）：{' | '.join(errs[-3:])[:400]}"
                )
            time.sleep(0.02)
        raise TimeoutError(f"MCP 调用超时（{method}）")

    def initialize(self) -> None:
        self.call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "personal-ai-os", "version": "0.1"},
            },
            timeout=45,
        )
        self.notify("notifications/initialized")

    def close(self) -> None:
        for closer in (self.proc.stdin,):
            try:
                if closer:
                    closer.close()
            except Exception:
                pass
        try:
            self.proc.terminate()
        except Exception:
            pass


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _stdio_session(server: McpServer, method: str, params: dict[str, Any] | None, timeout: float) -> Any:
    """拉起服务器 → initialize → 调用一次 → 关闭（同步函数，在线程里跑）。"""
    command = _resolve_command(server.command)
    env = {**os.environ, **(server.env or {})}
    # npx 默认把缓存与日志写到用户目录（受限环境会拒绝，也会污染系统）；
    # 统一放进项目内 data/cache/npm，随项目迁移、可整体清理。
    cache_dir = Path(__file__).resolve().parents[2] / "data" / "cache" / "npm"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        env.setdefault("npm_config_cache", str(cache_dir))
        env.setdefault("npm_config_update_notifier", "false")
        env.setdefault("npm_config_fund", "false")
        env.setdefault("npm_config_audit", "false")
        env.setdefault("NPM_CONFIG_CACHE", str(cache_dir))
    except Exception:
        pass

    cli_args = list(server.args)
    base = os.path.basename(command).lower()
    if base.startswith("npx") and "--cache" not in cli_args:
        cli_args = ["--cache", str(cache_dir), *cli_args]

    cli = StdioRpc(command, cli_args, env)
    try:
        cli.initialize()
        res = cli.call(method, params, timeout=timeout)
        if "error" in res:
            raise RuntimeError(f"MCP 返回错误：{res['error']}")
        return res.get("result")
    finally:
        cli.close()


async def _with_session(server: McpServer, fn: Callable[[Any], Coroutine[Any, Any, Any]]) -> Any:
    """HTTP 走官方 SDK；stdio 走自建 Popen 客户端（受限环境也能用）。"""
    if server.transport == "stdio":
        raise HTTPException(status_code=500, detail="stdio 传输请使用 _stdio_session")

    try:
        from mcp import ClientSession  # type: ignore
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"未安装 mcp 依赖：{e}（pip install mcp）")

    try:
        from mcp.client.streamable_http import streamable_http_client as http_client  # type: ignore
    except Exception:
        try:
            from mcp.client.streamable_http import streamablehttp_client as http_client  # type: ignore
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"当前 mcp 版本不支持 http 传输：{e}")
    async with http_client(server.url) as conn:
        read, write = conn[0], conn[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def _tool_to_openai(server: McpServer, tool: Any) -> dict[str, Any]:
    """把 MCP 工具（dict 或对象）转换成 OpenAI function 调用格式。"""
    schema = _field(tool, "inputSchema") or {}
    desc = _field(tool, "description") or ""
    name = _field(tool, "name") or ""
    return {
        "type": "function",
        "function": {
            "name": f"{server.id}__{name}",
            "description": f"[{server.name or server.id}] {desc}"[:1000],
            "parameters": schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
        },
        "_mcp": {"server_id": server.id, "tool": name},
    }


async def list_server_tools(server: McpServer, use_cache: bool = True) -> list[dict[str, Any]]:
    cached = _tools_cache.get(server.id)
    if use_cache and cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]

    if server.transport == "stdio":
        result = await asyncio.to_thread(_stdio_session, server, "tools/list", {}, 60)
        raw = (result or {}).get("tools") or []
    else:

        async def _do(session: Any) -> list[Any]:
            res = await session.list_tools()
            return list(getattr(res, "tools", None) or [])

        raw = await _with_session(server, _do)

    tools = [_tool_to_openai(server, t) for t in raw]
    _tools_cache[server.id] = (time.time(), tools)
    return tools


async def aggregate_tools(server_ids: list[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """汇总所有启用服务器的工具；返回 (工具清单, 错误信息列表)。"""
    tools: list[dict[str, Any]] = []
    errors: list[str] = []
    for s in _load().servers:
        if not s.enabled:
            continue
        if server_ids and s.id not in server_ids:
            continue
        try:
            tools += await list_server_tools(s)
        except HTTPException as e:
            errors.append(f"{s.name or s.id}: {e.detail}")
        except Exception as e:  # 子进程启动失败等
            errors.append(f"{s.name or s.id}: {type(e).__name__}: {e}")
    return tools, errors


@router.get("/servers")
def get_servers():
    cfg = _load()
    out = []
    for s in cfg.servers:
        cached = _tools_cache.get(s.id)
        out.append({**s.model_dump(), "tool_count": len(cached[1]) if cached else None})
    return {"ok": True, "servers": out}


@router.post("/servers")
def save_servers(cfg: McpConfig):
    """整表保存（前端增删改后提交）。"""
    data = cfg.model_dump()
    for s in data["servers"]:
        if not s.get("id"):
            s["id"] = f"m{int(time.time() * 1000) % 10_000_000}"
        if not s.get("name"):
            s["name"] = s["id"]
    _save(McpConfig(**data))
    _tools_cache.clear()
    return {"ok": True, "servers": data["servers"]}


@router.delete("/servers/{sid}")
def delete_server(sid: str):
    cfg = _load()
    cfg.servers = [s for s in cfg.servers if s.id != sid]
    _save(cfg)
    _tools_cache.pop(sid, None)
    return {"ok": True}


@router.post("/servers/{sid}/test")
async def test_server(sid: str):
    """拉起服务器并列工具（验证配置是否可用）。"""
    s = _server(sid)
    started = time.time()
    try:
        tools = await list_server_tools(s, use_cache=False)
    except HTTPException as e:
        return {"ok": False, "error": e.detail}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {
        "ok": True,
        "latency_ms": int((time.time() - started) * 1000),
        "tools": [{"name": t["_mcp"]["tool"], "description": t["function"]["description"][:200]} for t in tools],
    }


@router.get("/tools")
async def get_tools(refresh: bool = False):
    if refresh:
        _tools_cache.clear()
    tools, errors = await aggregate_tools()
    return {
        "ok": True,
        "errors": errors,
        "tools": [
            {
                "full_name": t["function"]["name"],
                "server_id": t["_mcp"]["server_id"],
                "tool": t["_mcp"]["tool"],
                "description": t["function"]["description"],
                "parameters": t["function"]["parameters"],
            }
            for t in tools
        ],
    }


async def call_tool_direct(server_id: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """供内部（工具调用循环）使用：不抛异常，返回 {ok, content|error}。"""
    try:
        s = _server(server_id)
    except HTTPException as e:
        return {"ok": False, "error": e.detail}

    try:
        if s.transport == "stdio":
            result = await asyncio.to_thread(
                _stdio_session, s, "tools/call", {"name": tool, "arguments": arguments or {}}, 180
            )
            texts: list[str] = []
            for c in (result or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "text":
                    texts.append(str(c.get("text", "")))
                elif _field(c, "text"):
                    texts.append(str(_field(c, "text")))
            return {
                "ok": True,
                "is_error": bool((result or {}).get("isError")),
                "content": "\n".join(texts)[:8000] or json.dumps(result, ensure_ascii=False)[:2000],
            }

        async def _do(session: Any) -> Any:
            return await session.call_tool(tool, arguments or {})

        res = await asyncio.wait_for(_with_session(s, _do), timeout=180)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "工具调用超时（180 秒）"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    texts2: list[str] = []
    for c in (getattr(res, "content", None) or []):
        t = getattr(c, "text", None)
        if t:
            texts2.append(str(t))
    return {
        "ok": True,
        "is_error": bool(getattr(res, "isError", False)),
        "content": "\n".join(texts2)[:8000] or str(res)[:2000],
    }


@router.post("/call")
async def call_tool(req: McpCallRequest):
    """直接调用某个 MCP 工具（前端逐次确认后调用）。"""
    res = await call_tool_direct(req.server_id, req.tool, req.arguments)
    if not res.get("ok"):
        return res
    return {"ok": True, "is_error": res.get("is_error", False), "content": res.get("content", "")}
