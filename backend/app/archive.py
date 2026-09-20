"""报告存档：把背调/情报类报告按公司归档到 data/intelligence/<公司>/。

约定见 docs/数据存储约定.md：
    data/intelligence/<公司名>/<YYYY-MM-DD-HHMM>-背调.md    报告正文（带 front-matter）
    data/intelligence/<公司名>/<YYYY-MM-DD-HHMM>-facts.json 风控体检事实（用于复算与复盘）

文件名只用安全字符；读写都做路径穿越校验，保证接口不会越出 data/intelligence。
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTEL_DIR = PROJECT_ROOT / "data" / "intelligence"
# 允许归档的根目录白名单（相对 data/；防止接口被用来写任意路径）
ALLOWED_ROOTS = ("intelligence", "knowledge", "knowledge/_行业", "projects", "review", "decisions", "inbox")

_SAFE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._\-]+")


def root_dir(root: str = "intelligence") -> Path:
    r = (root or "intelligence").strip().strip("/\\")
    if r not in ALLOWED_ROOTS:
        r = "intelligence"
    return PROJECT_ROOT / "data" / Path(r)


def safe_name(name: str, fallback: str = "未命名") -> str:
    """文件名安全化：保留中日韩文字与字母数字，其余转下划线。

    注意兼容性：除了 CJK 常用区，其他非 ASCII 字母（如带声调拼音、日文假名外的符号）
    用 isalnum() 兜底保留，避免中文/外语公司名被整段清空。
    """
    s = (name or "").strip()
    s = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in s)
    s = _SAFE.sub("_", s)[:80].strip("._-")
    return s or fallback


def _company_dir(company: str, root: str = "intelligence") -> Path:
    return root_dir(root) / safe_name(company, "未命名公司")


def _resolve(company: str, file: str, root: str = "intelligence") -> Path | None:
    """返回 <根目录>/<公司目录>/<file> 的绝对路径；越界或不存在返回 None。"""
    d = _company_dir(company, root)
    target = (d / safe_name(file, "x")).resolve()
    try:
        target.relative_to(d.resolve())
    except ValueError:
        return None
    return target if target.is_file() else None


def save_report(company: str, content: str, kind: str = "背调",
                meta: dict[str, Any] | None = None,
                facts: dict[str, Any] | None = None,
                root: str = "intelligence") -> dict[str, Any]:
    """写报告 + 可选事实快照，返回归档信息。root 见 ALLOWED_ROOTS。"""
    d = _company_dir(company, root)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    base = f"{stamp}-{safe_name(kind, '报告')}"
    md = d / f"{base}.md"
    n = 2
    while md.exists():
        md = d / f"{base}({n}).md"
        n += 1

    head = {
        "company": company.strip(),
        "kind": kind,
        "title": f"{company.strip()} · {kind}",
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **(meta or {}),
    }
    fm = "\n".join(f"{k}: {v}" for k, v in head.items() if v not in (None, ""))
    md.write_text(f"---\n{fm}\n---\n\n{content.strip()}\n", "utf-8")

    facts_path = ""
    if facts:
        fp = md.with_name(md.stem + "-facts.json")
        fp.write_text(json.dumps(facts, ensure_ascii=False, indent=2), "utf-8")
        facts_path = fp.name

    rel = md.relative_to(PROJECT_ROOT).as_posix()
    return {"ok": True, "file": md.name, "facts_file": facts_path, "rel_path": rel, "dir": d.relative_to(PROJECT_ROOT).as_posix()}


def list_reports(company: str = "", limit: int = 60, root: str = "intelligence") -> list[dict[str, Any]]:
    """列出存档报告（可按公司/行业过滤），按修改时间倒序。"""
    base = root_dir(root)
    if not base.exists():
        return []
    dirs = [_company_dir(company, root)] if company.strip() else [p for p in base.iterdir() if p.is_dir()]
    rows: list[dict[str, Any]] = []
    for d in dirs:
        if not d.exists():
            continue
        for p in d.glob("*.md"):
            try:
                text = p.read_text("utf-8")
            except Exception:
                text = ""
            meta: dict[str, str] = {}
            if text.startswith("---"):
                for ln in text.split("---")[1].splitlines():
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                        meta[k.strip()] = v.strip()
            title = meta.get("title") or f"{d.name} · {meta.get('kind', '报告')}"
            rows.append({
                "company": d.name,
                "file": p.name,
                "title": title,
                "saved_at": meta.get("saved_at", ""),
                "kind": meta.get("kind", "报告"),
                "risk": meta.get("risk") or meta.get("risk_level", ""),
                "size": p.stat().st_size,
                "rel_path": p.relative_to(PROJECT_ROOT).as_posix(),
                "mtime": p.stat().st_mtime,
            })
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows[: max(1, min(300, limit))]


class SaveRequest(BaseModel):
    company: str
    content: str
    kind: str = "背调"
    meta: dict[str, Any] = {}
    facts: dict[str, Any] = {}
    root: str = "intelligence"


@router.post("/archive/reports")
def archive_save(req: SaveRequest):
    if not req.content.strip():
        return {"ok": False, "error": "内容为空"}
    return save_report(req.company, req.content, req.kind, req.meta, req.facts, req.root)


@router.get("/archive/reports")
def archive_list(company: str = "", limit: int = 60, root: str = "intelligence"):
    return {"ok": True, "items": list_reports(company, limit, root), "dir": root_dir(root).relative_to(PROJECT_ROOT).as_posix()}


@router.get("/archive/reports/read")
def archive_read(company: str, file: str, root: str = "intelligence"):
    p = _resolve(company, file, root)
    if not p:
        return {"ok": False, "error": "文件不存在或路径非法"}
    return {"ok": True, "file": p.name, "content": p.read_text("utf-8")}


@router.delete("/archive/reports")
def archive_delete(company: str, file: str, root: str = "intelligence"):
    p = _resolve(company, file, root)
    if not p:
        return {"ok": False, "error": "文件不存在或路径非法"}
    fp = p.with_name(p.stem + "-facts.json")
    p.unlink(missing_ok=True)
    fp.unlink(missing_ok=True)
    return {"ok": True, "deleted": p.name}
