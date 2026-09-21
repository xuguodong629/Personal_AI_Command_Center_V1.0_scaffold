"""确定性匹配单元测试（规范 §18：第一阶段必须可在无 AI 条件下运行）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from aios.modules.jic.domain.matching import RULE_VERSION, score_job

pytestmark = pytest.mark.unit

PROFILE = {
    "version": "profile-test",
    "skills": ["渠道", "经销商", "回款"],
    "locations": ["河南", "郑州"],
    "seniority": "manager",
    "salary_min": 12000,
    "salary_max": 18000,
    "exclude_words": ["校招", "实习", "派遣"],
}


def _job(**over) -> dict:
    base = {
        "title": "区域销售经理",
        "description": "负责河南区域渠道开发与经销商维护，完成回款指标",
        "location": "郑州",
        "salary_text": "15-20K",
        "seniority": "manager",
        "published_at": datetime.now(timezone.utc) - timedelta(days=2),
    }
    base.update(over)
    return base


def test_given_fully_matching_job_when_scored_then_high_and_explainable():
    result = score_job(_job(), PROFILE)
    assert result.score >= 80
    assert result.rule_version == RULE_VERSION
    assert result.parts["skills"] > 0 and result.parts["location"] == 20.0
    assert any("技能命中" in r for r in result.reasons)


def test_given_location_mismatch_when_scored_then_zero_location_points_and_gap():
    result = score_job(_job(location="成都"), PROFILE)
    assert result.parts["location"] == 0.0
    assert any("地点不符" in g for g in result.gaps)
    assert result.score < 80


def test_given_excluded_word_when_scored_then_preference_zero():
    result = score_job(_job(title="渠道实习生"), PROFILE)
    assert result.parts["preference"] == 0.0
    assert any("命中排除词" in g for g in result.gaps)


def test_given_salary_below_expectation_when_scored_then_salary_zero():
    result = score_job(_job(salary_text="6-8K"), PROFILE)
    assert result.parts["salary"] == 0.0
    assert any("低于期望" in g for g in result.gaps)


def test_given_old_posting_when_scored_then_recency_reduced():
    old = datetime.now(timezone.utc) - timedelta(days=90)
    result = score_job(_job(published_at=old), PROFILE)
    assert result.parts["recency"] < 10
    assert any("发布已" in g for g in result.gaps)


def test_given_deterministic_inputs_when_scored_twice_then_same_result():
    """可复算：同输入同输出（规范 §18）。"""
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    a = score_job(_job(), PROFILE, now=now)
    b = score_job(_job(), PROFILE, now=now)
    assert (a.score, a.parts) == (b.score, b.parts)
