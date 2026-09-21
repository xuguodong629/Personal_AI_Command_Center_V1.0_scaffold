"""AI Gateway 集成测试（规范 §21 / §25.2-5）：Schema 校验、重试、缓存版本、账本与降级。"""
from __future__ import annotations

import asyncio

import pytest
from aios.core.db import session_scope
from aios.core.errors import AIOSError
from aios.modules.ai_gateway import gateway as gateway_mod
from aios.modules.ai_gateway.gateway import AIGateway, cache_key
from aios.modules.ai_gateway.models import AIRun
from aios.modules.ai_gateway.prompts import load_prompt
from aios.modules.ai_gateway.providers import FakeProvider
from pydantic import BaseModel

pytestmark = pytest.mark.integration


class Posting(BaseModel):
    title: str
    company_name: str = ""


class Postings(BaseModel):
    postings: list[Posting] = []


@pytest.fixture(autouse=True)
def clear_ai_cache():
    gateway_mod._CACHE.clear()
    yield
    gateway_mod._CACHE.clear()


def _call(gw: AIGateway, *, response_prompt: str = "material", retries: int = 0):
    prompt = load_prompt("job_extraction.v1.md").with_variables({"material": response_prompt})
    from aios.modules.ai_gateway.port import AIOptions
    return asyncio.run(gw.generate_structured(purpose="job_extraction", prompt=prompt, schema=Postings,
                                              options=AIOptions(max_retries=retries)))


def test_given_valid_json_when_generated_then_schema_validated_and_ledger_written():
    gw = AIGateway(FakeProvider(response='{"postings":[{"title":"渠道经理","company_name":"某电器"}]}'))
    result = _call(gw)
    assert [p.title for p in result.output.postings] == ["渠道经理"]
    assert result.token_usage == 42
    with session_scope() as session:
        rows = session.query(AIRun).filter(AIRun.purpose == "job_extraction").all()
    assert rows, "ai_runs 账本必须有记录（规范 §21.1）"
    assert rows[-1].prompt_id == "job_extraction" and rows[-1].prompt_version == "1"
    assert rows[-1].status == "succeeded" and rows[-1].prompt_hash


def test_given_same_prompt_when_called_twice_then_second_is_cache_hit():
    gw = AIGateway(FakeProvider(response='{"postings":[{"title":"渠道经理"}]}'))
    first = _call(gw)
    second = _call(gw)
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert gw.provider.calls == 1


def test_given_cache_key_when_prompt_version_changes_then_key_changes():
    base = dict(provider="p", model="m", prompt_id="job_extraction", schema_version="1", payload="x")
    assert cache_key(**base, prompt_version="1") != cache_key(**base, prompt_version="2")


def test_given_invalid_json_when_generated_then_schema_error_not_silent_fallback():
    gw = AIGateway(FakeProvider(response='{"postings":[{"title": 123}]}'))
    with pytest.raises(AIOSError) as err:
        _call(gw)
    assert err.value.code.value == "AI_SCHEMA_INVALID"


def test_given_fenced_json_when_generated_then_extracted_and_validated():
    gw = AIGateway(FakeProvider(response='```json\n{"postings":[{"title":"区域经理"}]}\n```'))
    result = _call(gw)
    assert result.output.postings[0].title == "区域经理"


def test_given_transient_failure_when_retried_then_eventually_succeeds():
    gw = AIGateway(FakeProvider(response='{"postings":[{"title":"渠道经理"}]}', fail_times=1))
    result = _call(gw, retries=2)
    assert result.output.postings[0].title == "渠道经理"
    assert gw.provider.calls == 2


def test_given_all_attempts_fail_when_generated_then_provider_unavailable():
    gw = AIGateway(FakeProvider(response="{}", fail_times=99))
    with pytest.raises(AIOSError) as err:
        _call(gw, retries=1)
    assert err.value.code.value == "AI_PROVIDER_UNAVAILABLE"
    with session_scope() as session:
        failed = session.query(AIRun).filter(AIRun.status == "failed").count()
    assert failed >= 1, "失败的调用也必须留账本（规范 §21.1）"
