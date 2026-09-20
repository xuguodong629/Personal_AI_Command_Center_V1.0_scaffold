from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from urllib.parse import urlparse
import os
import webbrowser

from app.ai import router as ai_router
from app.archive import router as archive_router
from app.industry import router as industry_router
from app.interview_store import router as interview_router
from app.mcp_host import router as mcp_router
from app.risk import router as risk_router
from app.signals import router as signals_router
from app.skills import router as skills_router
from app.voice import router as voice_router


class UTF8JSONResponse(JSONResponse):
    """所有 JSON 响应显式声明 charset=utf-8。

    默认的 `application/json` 不带 charset 时，部分客户端（PowerShell 的
    Invoke-RestMethod、旧版 curl 等）会按 ISO-8859-1 解码中文 → 拿到乱码。
    浏览器 fetch 不受影响，但为了让脚本/命令行也拿到正常中文，这里统一声明。
    """

    media_type = "application/json; charset=utf-8"


app = FastAPI(title="Personal AI Command Center API", version="0.2.0",
              default_response_class=UTF8JSONResponse)

# 前端开发服务器直连后端；后续 Tauri 壳（tauri://localhost）也走这里
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5199", "http://127.0.0.1:5199",
        "http://localhost:4173", "http://127.0.0.1:4173",
        "tauri://localhost", "https://tauri.localhost",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai_router)
app.include_router(risk_router)
app.include_router(industry_router)
app.include_router(signals_router)
app.include_router(archive_router)
app.include_router(voice_router)
app.include_router(interview_router)
app.include_router(mcp_router)
app.include_router(skills_router)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Config(BaseModel):
    # 知识库默认指向项目内的 data/knowledge（见 docs/数据存储约定.md），开箱即用
    knowledge_base_path: str = str(PROJECT_ROOT / "data" / "knowledge")
    ai_provider: str = "deepseek"
    review_required: bool = True

CONFIG = Config(
    knowledge_base_path=os.getenv("AIOS_KNOWLEDGE_PATH") or str(PROJECT_ROOT / "data" / "knowledge")
)

@app.get("/api/health")
def health():
    return {"status":"online","service":"ai-os-core","version":"0.2.0"}

@app.get("/api/config")
def get_config():
    return CONFIG

@app.post("/api/config")
def set_config(config: Config):
    global CONFIG
    CONFIG = config
    return CONFIG

@app.get("/api/knowledge/stats")
def knowledge_stats():
    root = Path(CONFIG.knowledge_base_path) if CONFIG.knowledge_base_path else None
    if not root or not root.exists():
        return {"path": str(root) if root else "", "markdown_files": 0, "status":"not_configured"}
    files = list(root.rglob("*.md"))
    return {"path":str(root),"markdown_files":len(files),"status":"ready"}


# ---------- 外部链接：由后端调用系统默认浏览器打开 ----------
# 桌面端（Tauri）里点击 <a href> 会让应用窗口自身跳转/新开窗口，关掉即整程序退出；
# 因此前端拦截外链后调用本接口，交由系统浏览器打开（不改动 Rust，无需重新编译）。
class OpenUrlRequest(BaseModel):
    url: str = ""


@app.post("/api/system/open-url")
def system_open_url(req: OpenUrlRequest):
    u = (req.url or "").strip()
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        return {"ok": False, "error": "只允许打开 http/https 链接"}
    try:
        webbrowser.open(u)
    except Exception as e:
        return {"ok": False, "error": f"打开失败：{e}"}
    return {"ok": True, "url": u}


# ---------- 独立运行：前端构建产物（frontend/dist）由后端一并托管 ----------
# 存在 dist 时：直接访问 http://127.0.0.1:8787 就是完整界面（单进程，无需 Node 常驻，不依赖 Dify）
# 开发模式仍可用：npm run dev（5173）+ 本后端（8787）
DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="ui")
