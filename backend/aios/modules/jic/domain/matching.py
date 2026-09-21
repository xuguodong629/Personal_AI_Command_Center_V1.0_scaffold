"""确定性匹配（规范 §18）：**第一阶段必须可在无 AI 条件下运行**。

特征：技能重叠、地点/工作模式、资历、排除词、发布时间、薪资、用户偏好权重。
AI 只用于提取/解释/摘要（见 ai_gateway），不得单独决定自动外部动作。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from aios.modules.jic.domain.normalize import normalize_location, parse_salary_text

RULE_VERSION = "rules-1.0.0"

DEFAULT_WEIGHTS: dict[str, float] = {
    "skills": 30.0,
    "location": 20.0,
    "seniority": 15.0,
    "salary": 15.0,
    "recency": 10.0,
    "preference": 10.0,
}


@dataclass
class MatchResult:
    score: float
    parts: dict[str, float]
    reasons: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    rule_version: str = RULE_VERSION


def _skill_overlap(text: str, skills: list[str]) -> tuple[float, list[str]]:
    if not skills:
        return 0.0, []
    low = (text or "").lower()
    hits = [s for s in skills if s and s.lower() in low]
    return len(hits) / len(skills), hits


def score_job(job: dict[str, Any], profile: dict[str, Any],
              *, now: datetime | None = None) -> MatchResult:
    """对单条职位做确定性评分（0–100）。`job` 与 `profile` 都是纯字典，便于单测。"""
    now = now or datetime.now(timezone.utc)
    weights = {**DEFAULT_WEIGHTS, **(profile.get("weights") or {})}
    parts: dict[str, float] = {}
    reasons: list[str] = []
    gaps: list[str] = []

    # ① 技能重叠
    text = " ".join([job.get("title", ""), job.get("description", ""), job.get("salary_text", "")])
    ratio, hits = _skill_overlap(text, profile.get("skills") or [])
    parts["skills"] = round(weights["skills"] * ratio, 2)
    if hits:
        reasons.append("技能命中：" + "、".join(hits[:6]))
    elif profile.get("skills"):
        gaps.append("技能未命中：材料未出现目标技能词")

    # ② 地点 / 工作模式
    want_locations = [normalize_location(x) for x in (profile.get("locations") or []) if x]
    have_location = normalize_location(job.get("location", ""))
    location_matched = True
    if not want_locations:
        parts["location"] = round(weights["location"] * 0.6, 2)
    elif have_location and any(w and (w in have_location or have_location in w) for w in want_locations):
        parts["location"] = weights["location"]
        reasons.append(f"地点匹配：{job.get('location', '')}")
    else:
        parts["location"] = 0.0
        location_matched = False
        gaps.append(f"地点不符：{job.get('location', '') or '材料未见'}")

    # ③ 资历
    want_seniority = (profile.get("seniority") or "").strip()
    have_seniority = (job.get("seniority") or "").strip()
    if not want_seniority:
        parts["seniority"] = round(weights["seniority"] * 0.6, 2)
    elif want_seniority == have_seniority:
        parts["seniority"] = weights["seniority"]
        reasons.append(f"资历匹配：{have_seniority}")
    else:
        parts["seniority"] = round(weights["seniority"] * 0.3, 2)
        gaps.append(f"资历差异：岗位 {have_seniority or '材料未见'} / 期望 {want_seniority}")

    # ④ 薪资
    lo, hi = parse_salary_text(job.get("salary_text", ""))
    want_min = int(profile.get("salary_min") or 0)
    want_max = int(profile.get("salary_max") or 0)
    if not lo and not hi:
        parts["salary"] = round(weights["salary"] * 0.4, 2)
        gaps.append("薪资未公开")
    elif want_min and hi and hi < want_min:
        parts["salary"] = 0.0
        gaps.append(f"薪资低于期望下限 {want_min}")
    elif want_max and lo and lo > want_max:
        parts["salary"] = round(weights["salary"] * 0.5, 2)
        reasons.append(f"薪资高于期望上限 {want_max}（可谈）")
    else:
        parts["salary"] = weights["salary"]
        reasons.append("薪资落在期望区间")

    # ⑤ 新鲜度
    published = job.get("published_at")
    if isinstance(published, str):
        try:
            published = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            published = None
    if published is None:
        parts["recency"] = round(weights["recency"] * 0.4, 2)
        gaps.append("发布时间未覆盖")
    else:
        days = (now - published).days
        if days <= 7:
            parts["recency"] = weights["recency"]
        elif days <= 30:
            parts["recency"] = round(weights["recency"] * 0.6, 2)
        else:
            parts["recency"] = round(weights["recency"] * 0.2, 2)
            gaps.append(f"发布已 {days} 天")

    # ⑥ 排除词（规范 §18：排除词是基础特征）
    low = (job.get("title", "") + job.get("description", "")).lower()
    excluded = [w for w in (profile.get("exclude_words") or []) if w and w.lower() in low]
    if excluded:
        parts["preference"] = 0.0
        gaps.append("命中排除词：" + "、".join(excluded[:5]))
    else:
        parts["preference"] = weights["preference"]
        reasons.append("未命中排除词")

    total = round(max(0.0, min(100.0, sum(parts.values()))), 2)
    # 地点封顶：候选人明确限定地区时，地点不符不得进入"优先投递"区间（与岗位雷达规则层同一口径）
    if not location_matched and want_locations:
        total = min(total, 74.0)
        gaps.append("地点不符：按规则封顶，最高只能到「谨慎」")
    return MatchResult(score=total, parts=parts, reasons=reasons, gaps=gaps)


def is_recent(published: datetime | None, days: int = 30, *, now: datetime | None = None) -> bool:
    if published is None:
        return False
    return (now or datetime.now(timezone.utc)) - published <= timedelta(days=days)
