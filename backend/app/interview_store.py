"""面试工作区：每场面试独立存档，可分类检索、随时调取。

存储：data/interview/<session_id>.json（本地、可迁移、一个人一个文件夹）
字段：标题 / 公司 / 面试官人格 / JD / 阶段进度 / 标签 / 消息 / 复盘报告 / 时间戳
"""
import json
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/interview")
STORE_DIR = Path(__file__).resolve().parents[2] / "data" / "interview"


class SessionMessage(BaseModel):
    role: str
    content: str


class Session(BaseModel):
    id: str = ""
    title: str = ""
    company: str = ""
    persona: str = "region_director"
    jd: str = ""
    stage: str = "intro"
    round_no: int = 1
    progress: str = ""
    finished: bool = False
    tags: list[str] = []
    created_at: float = 0
    updated_at: float = 0
    messages: list[SessionMessage] = []
    review: str = ""


class AutoTagRequest(BaseModel):
    provider_id: str


def _path(sid: str) -> Path:
    return STORE_DIR / f"{sid}.json"


def _load(sid: str) -> dict[str, Any] | None:
    p = _path(sid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return None


def _save(data: dict[str, Any]) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    _path(data["id"]).write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


@router.get("/sessions")
def list_sessions(q: str = "", tag: str = ""):
    """列表（按更新时间倒序）；q 为关键词（标题/公司/内容），tag 为标签筛选。"""
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for p in STORE_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text("utf-8"))
        except Exception:
            continue
        if tag and tag not in (d.get("tags") or []):
            continue
        if q:
            hay = json.dumps(
                {
                    "title": d.get("title"),
                    "company": d.get("company"),
                    "tags": d.get("tags"),
                    "messages": d.get("messages"),
                },
                ensure_ascii=False,
            )
            if q not in hay:
                continue
        items.append(
            {
                "id": d.get("id"),
                "title": d.get("title") or "未命名面试",
                "company": d.get("company") or "",
                "persona": d.get("persona") or "",
                "finished": bool(d.get("finished")),
                "progress": d.get("progress") or "",
                "tags": d.get("tags") or [],
                "created_at": d.get("created_at") or 0,
                "updated_at": d.get("updated_at") or 0,
                "message_count": len(d.get("messages") or []),
                "has_review": bool(d.get("review")),
            }
        )
    items.sort(key=lambda x: x.get("updated_at") or 0, reverse=True)
    return {"ok": True, "sessions": items}


@router.get("/tags")
def list_tags():
    """所有标签及数量，用于筛选。"""
    counts: dict[str, int] = {}
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    for p in STORE_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text("utf-8"))
        except Exception:
            continue
        for t in d.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    tags = [{"tag": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
    return {"ok": True, "tags": tags}


@router.post("/sessions")
def create_session(body: Session):
    now = time.time()
    sid = uuid.uuid4().hex[:12]
    data = body.model_dump()
    data.update({"id": sid, "created_at": now, "updated_at": now})
    if not data.get("title"):
        data["title"] = f"面试 · {time.strftime('%Y-%m-%d %H:%M', time.localtime(now))}"
    _save(data)
    return {"ok": True, "session": data}


@router.get("/sessions/{sid}")
def get_session(sid: str):
    d = _load(sid)
    if not d:
        raise HTTPException(status_code=404, detail="面试记录不存在")
    return {"ok": True, "session": d}


@router.put("/sessions/{sid}")
def update_session(sid: str, body: Session):
    old = _load(sid)
    if not old:
        raise HTTPException(status_code=404, detail="面试记录不存在")
    data = body.model_dump()
    data["id"] = sid
    data["created_at"] = old.get("created_at") or time.time()
    data["updated_at"] = time.time()
    if not data.get("title"):
        data["title"] = old.get("title") or f"面试 · {time.strftime('%Y-%m-%d %H:%M')}"
    _save(data)
    return {"ok": True, "session": data}


@router.delete("/sessions/{sid}")
def delete_session(sid: str):
    p = _path(sid)
    if not p.exists():
        raise HTTPException(status_code=404, detail="面试记录不存在")
    p.unlink()
    return {"ok": True}


@router.post("/sessions/{sid}/auto-tag")
async def auto_tag(sid: str, req: AutoTagRequest):
    """让模型按内容建议标签（岗位方向 / 行业 / 公司 / 面试官 / 结论），便于分类存档。"""
    d = _load(sid)
    if not d:
        raise HTTPException(status_code=404, detail="面试记录不存在")
    try:
        from app.ai import _llm_call, _load_providers
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"无法加载模型模块：{e}")

    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        raise HTTPException(status_code=400, detail="模型不存在或已被删除")

    msgs = d.get("messages") or []
    transcript = "\n".join(f"{m.get('role')}: {str(m.get('content'))[:300]}" for m in msgs)[-6000:]
    user = (
        f"公司：{d.get('company') or '未指定'}\n"
        f"面试官：{d.get('persona')}\n"
        f"是否完成：{'是' if d.get('finished') else '否'}\n"
        f"面试记录节选：\n{transcript}\n\n"
        "请给出 3-6 个分类标签（中文、每个 2-8 字），覆盖：岗位方向、行业、目标公司、面试官角色、结果或状态。"
        "只输出标签，用逗号分隔，不要解释。"
    )
    r = await _llm_call(provider, [
        {"role": "system", "content": "你是面试记录整理助手，只负责给标签。"},
        {"role": "user", "content": user},
    ])
    if not r.get("ok"):
        raise HTTPException(status_code=502, detail=r.get("error", "标签生成失败"))
    tags = [t.strip() for t in str(r["content"]).replace("，", ",").split(",") if t.strip()][:6]
    return {"ok": True, "tags": tags}
