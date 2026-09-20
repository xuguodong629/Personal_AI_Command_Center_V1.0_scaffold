"""技能（Skills）：目录 + SKILL.md 指令包，按需注入提示词；支持自建/编辑/导入公开技能。

结构：data/skills/<skill-name>/SKILL.md
SKILL.md 支持简单 front-matter：
---
title: 显示名
description: 一句话说明（用于选择技能）
---
正文即注入模型的指令（渐进式：只在用到时才注入，省 token）。
"""
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/skills")
SKILLS_DIR = Path(__file__).resolve().parents[2] / "data" / "skills"

FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)

# 首次运行自动生成的内置技能（贴合求职场景）
SEED: dict[str, str] = {
    "jd-breakdown": """---
title: JD 拆解
description: 把一段岗位 JD 拆成可核实的要点与面试问题
---
你是资深招聘顾问。请把用户给出的 JD 拆解为：
1. **硬性门槛**（学历/年限/证书/出差）—— 逐条列出，并标注「可谈/不可谈」判断依据
2. **真实职责**（去掉套话，用一句话说清每天在干什么）
3. **考核口径**（KPI 是出货、回款、动销还是利润）
4. **隐藏信息**（从措辞推断的团队现状与风险）
5. **面试必问 8 题**（针对模糊处提问，附提问话术）
只依据 JD 原文，未写明的写「JD 未写明，需面试确认」。输出用 Markdown 表格。""",
    "resume-tailor": """---
title: 简历定向润色
description: 按目标 JD 定向改写简历，突出量化成果
---
你是简历优化专家。基于给定的 JD 与候选人简历：
1. 输出**匹配度自评表**（维度 / 匹配度 / 依据）
2. 按该 JD 重写简历要点：每条用「动作 + 场景 + 量化结果」，优先保留与 JD 强相关的经历
3. 指出**最该删掉的 3 项**内容及原因
4. 给出**缺口补强建议**（哪 2-3 个能力最该补，怎么补）
不得编造候选人没有的经历；数据缺失处标注「待补」。""",
    "interview-drill": """---
title: 面试出题与追问
description: 针对岗位与简历生成面试题，并按 STAR 追问
---
你是面试官。请围绕目标岗位与候选人履历：
1. 输出**12 题**面试题清单（开场 / 履历深挖 / 专业题 / 压力题 / 反问），每题标明考察点
2. 对其中 4 道核心题，写出**STAR 追问链**（缺数据 → 问什么；缺你的动作 → 问什么）
3. 给每题一个「好回答的骨架」（不替候选人编造内容，只给结构）
输出 Markdown 表格。""",
    "intel-brief": """---
title: 情报摘要与风险标记
description: 把一堆资料压缩成结构化情报简报
---
你是情报分析员。请把用户提供的材料整理为：
| 事实 | 来源 | 影响（对求职/经营） | 可信度 | 待核实 |
要求：① 只写材料里有的事实，推断单独放「推断」列并标注依据；② 明确区分「利好 / 利空 / 中性」；
③ 最后给出 3 条「下一步动作」。禁止编造数据与时间。""",
}


class SkillBody(BaseModel):
    name: str
    content: str


class SkillRunRequest(BaseModel):
    provider_id: str
    input: str = ""
    context: str = ""


class SkillImportRequest(BaseModel):
    url: str
    name: str = ""


def _meta(content: str) -> tuple[dict[str, str], str]:
    m = FRONT_MATTER.match(content)
    if not m:
        return {}, content
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, content[m.end():]


def _ensure_seed() -> None:
    if SKILLS_DIR.exists() and any(SKILLS_DIR.glob("*/SKILL.md")):
        return
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in SEED.items():
        d = SKILLS_DIR / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(content, "utf-8")


def _safe_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9_\-]", "-", (name or "").strip()).strip("-")
    if not n:
        raise HTTPException(status_code=400, detail="技能名不合法（仅字母数字与 - _）")
    return n[:60]


def _skill_file(name: str) -> Path:
    return SKILLS_DIR / _safe_name(name) / "SKILL.md"


def _read_skill(name: str) -> dict[str, Any]:
    p = _skill_file(name)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"技能不存在：{name}")
    content = p.read_text("utf-8")
    meta, body = _meta(content)
    return {
        "name": _safe_name(name),
        "title": meta.get("title") or _safe_name(name),
        "description": meta.get("description", ""),
        "content": content,
        "body": body,
        "updated_at": p.stat().st_mtime,
        "path": str(p),
    }


@router.get("")
def list_skills():
    _ensure_seed()
    items = []
    for p in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        meta, body = _meta(p.read_text("utf-8"))
        items.append(
            {
                "name": p.parent.name,
                "title": meta.get("title") or p.parent.name,
                "description": meta.get("description", ""),
                "chars": len(body),
                "updated_at": p.stat().st_mtime,
            }
        )
    items.sort(key=lambda x: x["updated_at"], reverse=True)
    return {"ok": True, "skills": items}


@router.get("/{name}")
def get_skill(name: str):
    s = _read_skill(name)
    s.pop("body", None)
    return {"ok": True, "skill": s}


@router.post("")
def save_skill(body: SkillBody):
    p = _skill_file(body.name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.content, "utf-8")
    return {"ok": True, "skill": _read_skill(body.name) | {"body": None}}


@router.delete("/{name}")
def delete_skill(name: str):
    d = SKILLS_DIR / _safe_name(name)
    if not d.exists():
        raise HTTPException(status_code=404, detail="技能不存在")
    (d / "SKILL.md").unlink(missing_ok=True)
    try:
        d.rmdir()
    except OSError:
        pass
    return {"ok": True}


@router.post("/{name}/run")
async def run_skill(name: str, req: SkillRunRequest):
    """按技能指令执行一次（用直连模型）。"""
    skill = _read_skill(name)
    try:
        from app.ai import _llm_call, _load_providers
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"无法加载模型模块：{e}")

    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        raise HTTPException(status_code=400, detail="模型不存在或已被删除")

    sys_prompt = (
        f"【技能：{skill['title']}】\n{skill['body'].strip()}\n\n"
        "通用要求：全程中文；只依据给定内容，不得编造；缺失信息标「待补充」；输出用 Markdown。"
    )
    user = req.input.strip() or "（未提供输入）"
    if req.context.strip():
        user = f"{user}\n\n【补充材料】\n{req.context.strip()[:12000]}"

    r = await _llm_call(provider, [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user},
    ])
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error", "执行失败")}
    return {"ok": True, "content": r["content"], "model": provider.model, "skill": skill["title"]}


@router.post("/import")
def import_skill(req: SkillImportRequest):
    """从公开 URL 导入 SKILL.md（例如 GitHub raw 链接）。"""
    url = (req.url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请提供 http/https 链接")
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", "ignore")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"下载失败：{e}")
    if not raw.strip():
        raise HTTPException(status_code=400, detail="下载内容为空")
    meta, _body = _meta(raw)
    name = req.name or meta.get("name") or (url.rstrip("/").split("/")[-2] if "/" in url else "")
    name = _safe_name(name or f"imported-{int(time.time())}")
    p = SKILLS_DIR / name / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(raw, "utf-8")
    return {"ok": True, "name": name, "title": meta.get("title", name)}
