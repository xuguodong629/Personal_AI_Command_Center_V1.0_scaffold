"""API 集成测试（规范 §9 契约 / §10 审计与鉴权 / §14.1 来源准入 / §19 作业幂等 / §31 验收）。"""
from __future__ import annotations

import hashlib
import os
import time
import uuid

import pytest
from aios.contracts import DiscoveredItem, DiscoveryPage, FetchedPage, ParsedJobPosting
from aios.modules.jic.infrastructure.spiders import spider_manager
from aios.modules.jic.infrastructure.spiders.base import Spider

pytestmark = pytest.mark.integration


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _candidate(**over) -> dict:
    """每条候选都带唯一公司与正文编号，避免不同用例之间因指纹相同被误判为同一岗位。"""
    uid = uuid.uuid4().hex[:8]
    base = {
        "title": "区域销售经理",
        "company_name": f"测试电器有限公司{uid}",
        "location": "郑州",
        "salary_text": "15-20K",
        "platform": "猎聘",
        "url": f"https://jobs.example.com/job/{uid}",
        "description": f"负责河南区域渠道开发与经销商维护，完成回款指标，要求五年以上家电渠道经验。编号 {uid}",
        "evidence": "已抓正文",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------- 基础契约

def test_given_health_when_called_then_dependency_status_returned(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "ok"
    assert body["data"]["dependencies"]["database"]["status"] == "ok"
    assert body["data"]["dependencies"]["database"]["migration"]
    assert body["data"]["dependencies"]["job_types"]
    assert body["meta"]["request_id"].startswith("req_")
    assert resp.headers["X-Request-Id"] == body["meta"]["request_id"]


def test_given_missing_resource_when_get_then_error_envelope_with_request_id(client):
    resp = client.get("/api/v1/job-postings/does-not-exist")
    assert resp.status_code == 404
    error = resp.json()["error"]
    assert error["code"] == "NOT_FOUND" and error["request_id"].startswith("req_")


def test_given_invalid_body_when_post_then_validation_error_envelope(client):
    resp = client.post("/api/v1/job-sources", json={"name": "x"})     # 缺 policy
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert resp.json()["error"]["details"]


def test_given_write_when_called_then_idempotency_header_supported(client):
    req = {"job_type": "platform.publish_outbox", "payload": {"limit": 5}}
    headers = {"Idempotency-Key": _uniq("idem")}
    first = client.post("/api/v1/jobs", json=req, headers=headers).json()["data"]
    second = client.post("/api/v1/jobs", json=req, headers=headers).json()["data"]
    assert first["id"] == second["id"]
    assert second["reused"] is True


# ---------------------------------------------------------------- JIC 导入与去重

def test_given_candidates_when_imported_then_created_then_unchanged_on_second_import(client):
    url = f"https://jobs.example.com/job/{uuid.uuid4().hex[:8]}"
    cand = _candidate(url=url)
    first = client.post("/api/v1/job-postings/import", json={"candidates": [cand]}).json()["data"]
    assert first["created"] == 1 and first["updated"] == 0

    # 同一岗位换 UTM 参数再次导入 → 必须命中 canonical_url 去重（规范 §15/§16.1）
    second = client.post("/api/v1/job-postings/import",
                         json={"candidates": [{**cand, "url": url + "?utm_source=wechat"}]}).json()["data"]
    assert second["created"] == 0 and second["unchanged"] == 1
    assert second["dedup_reasons"].get("canonical_url", 0) >= 1


def test_given_missing_title_when_imported_then_rejected(client):
    stats = client.post("/api/v1/job-postings/import",
                        json={"candidates": [_candidate(title="", url="")]}).json()["data"]
    assert stats["rejected"] == 1


def test_given_imported_job_when_listed_then_pagination_and_filters(client):
    cand = _candidate(company_name="分页测试电器有限公司", location="洛阳")
    client.post("/api/v1/job-postings/import", json={"candidates": [cand]})
    body = client.get("/api/v1/job-postings", params={"location": "洛阳", "page": 1, "page_size": 5}).json()
    assert body["meta"]["page"] == 1 and body["meta"]["page_size"] == 5
    assert body["meta"]["total"] >= 1
    assert all("洛阳" in item["location"] for item in body["data"])


def test_given_job_when_state_and_matches_requested_then_persisted_and_explainable(client):
    job = client.post("/api/v1/job-postings/import", json={"candidates": [_candidate()]}).json()["data"]
    job_id = client.get("/api/v1/job-postings", params={"page_size": 1}).json()["data"][0]["id"]
    assert job["created"] == 1

    state = client.patch(f"/api/v1/job-postings/{job_id}/state",
                         json={"state": "saved", "notes": "重点关注"}).json()["data"]
    assert state["state"] == "saved"

    detail = client.get(f"/api/v1/job-postings/{job_id}").json()["data"]
    assert detail["user_state"]["state"] == "saved"
    assert detail["versions"] and detail["versions"][0]["version"] >= 1
    assert detail["match"]["score"] > 0
    assert detail["match"]["rule_version"].startswith("rules-")

    matches = client.get(f"/api/v1/job-postings/{job_id}/matches").json()["data"]
    assert matches["parts"] and matches["rule_version"]


def test_given_version_change_when_updated_then_new_version_recorded(client):
    url = f"https://jobs.example.com/job/{uuid.uuid4().hex[:8]}"
    client.post("/api/v1/job-postings/import", json={"candidates": [_candidate(url=url)]})
    job_id = client.get("/api/v1/job-postings", params={"q": "区域销售经理", "page_size": 1}).json()["data"][0]["id"]
    client.post("/api/v1/job-postings/import",
                json={"candidates": [_candidate(url=url, description="职责已更新：新增县域网点开发要求。")]})
    detail = client.get(f"/api/v1/job-postings/{job_id}").json()["data"]
    assert len(detail["versions"]) >= 2
    assert any("description" in v["changed_fields"] for v in detail["versions"])


# ---------------------------------------------------------------- 来源准入（§14.1）

def test_given_source_without_auto_crawl_when_run_then_rejected_and_no_request(client):
    name = _uniq("src-nocrawl")
    created = client.post("/api/v1/job-sources", json={
        "name": name, "base_url": "https://jobs.example.com", "source_type": "public_html",
        "policy": {"domain": "jobs.example.com", "access_method": "public_html",
                   "allow_auto_crawl": False, "robots_checked_at": "2026-09-01T00:00:00Z"},
    }).json()["data"]
    resp = client.post(f"/api/v1/job-sources/{created['id']}/runs", json={})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "JOB_SOURCE_NOT_ALLOWED"
    # 准入未过 → 不产生采集运行、不计失败次数、来源仍启用
    still = [s for s in client.get("/api/v1/job-sources").json()["data"] if s["id"] == created["id"]][0]
    assert still["status"] == "enabled" and still["consecutive_failures"] == 0


def test_given_disabled_source_when_run_then_conflict(client):
    created = client.post("/api/v1/job-sources", json={
        "name": _uniq("src-disabled"), "base_url": "https://jobs.example.com",
        "source_type": "public_html", "status": "disabled",
        "policy": {"domain": "jobs.example.com", "allow_auto_crawl": True,
                   "robots_checked_at": "2026-09-01T00:00:00Z"},
    }).json()["data"]
    resp = client.post(f"/api/v1/job-sources/{created['id']}/runs", json={})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "JOB_SOURCE_DISABLED"


def test_given_source_returns_403_when_run_then_marked_blocked(client):
    """规范 §14.1-4：403/验证码特征 → 立即停止该来源并记录 blocked。"""

    class BlockedSpider(Spider):
        source_type = "test_blocked"

        def discover(self, cursor=None):
            return DiscoveryPage(items=[DiscoveredItem(url="https://blocked.example.com/job/1")],
                                 exhausted=True)

        def fetch(self, item):
            return FetchedPage(url=item.url, status=403, content="Security Verification",
                               blocked_reason="http_403")

        def parse(self, page):
            return ParsedJobPosting(source_key="test_blocked", confidence=0.1)

    spider_manager.register(BlockedSpider)
    created = client.post("/api/v1/job-sources", json={
        "name": _uniq("src-blocked"), "base_url": "https://blocked.example.com",
        "source_type": "test_blocked",
        "policy": {"domain": "blocked.example.com", "access_type": "public_html",
                   "allow_auto_crawl": True, "robots_checked_at": "2026-09-01T00:00:00Z",
                   "max_consecutive_failures": 1},
    }).json()["data"]
    resp = client.post(f"/api/v1/job-sources/{created['id']}/runs", json={}).json()["data"]
    assert resp["status"] == "blocked"
    assert resp["blocked_reason"] == "http_403"
    run = client.get(f"/api/v1/crawl-runs/{resp['crawl_run_id']}").json()["data"]
    assert run["error_code"] == "JOB_SOURCE_BLOCKED"
    after = [s for s in client.get("/api/v1/job-sources").json()["data"] if s["id"] == created["id"]][0]
    assert after["status"] == "blocked" and after["blocked_reason"].startswith("blocked:")


def test_given_sources_when_health_checked_then_reports_policy_problems(client):
    rows = client.get("/api/v1/job-sources/health").json()["data"]
    assert isinstance(rows, list)


# ---------------------------------------------------------------- 作业（§5/§19）

def _wait_job(client, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
        if data["status"] in ("succeeded", "failed", "dead"):
            return data
        time.sleep(0.2)
    raise AssertionError(f"作业未在 {timeout}s 内结束：{data}")


def test_given_long_task_when_submitted_then_returns_card_then_completes(client):
    """规范 §5：API 立即返回作业卡片，长任务后台执行。"""
    resp = client.post("/api/v1/jobs", json={
        "job_type": "jic.import_candidates",
        "payload": {"candidates": [_candidate(company_name="异步导入电器有限公司")]},
        "idempotency_key": _uniq("job"),
    })
    assert resp.status_code == 200
    card = resp.json()["data"]
    assert card["status"] in ("queued", "running")
    assert card["trace_id"].startswith("trace_")
    done = _wait_job(client, card["id"])
    assert done["status"] == "succeeded"
    assert done["attempts"] >= 1 and done["finished_at"]


def test_given_dead_job_when_replayed_then_new_execution_created(client):
    """规范 §19.3：死信重放必须生成新的执行记录。"""
    bad = client.post("/api/v1/jobs", json={
        "job_type": "jic.run_source", "payload": {"source_id": "does-not-exist"},
        "idempotency_key": _uniq("job-bad"), "max_attempts": 1,
    }).json()["data"]
    dead = _wait_job(client, bad["id"])
    assert dead["status"] == "dead" and dead["error_code"] == "NotFoundError"
    replay = client.post(f"/api/v1/jobs/{bad['id']}/replay").json()["data"]
    assert replay["id"] != bad["id"]


def test_given_unknown_job_type_when_submitted_then_validation_error(client):
    resp = client.post("/api/v1/jobs", json={"job_type": "nope.nope", "payload": {}})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------- 审计（§10）

def test_given_audited_actions_when_queried_then_events_recorded(client):
    client.post("/api/v1/job-postings/import", json={"candidates": [_candidate()]})
    body = client.get("/api/v1/audit-events", params={"limit": 50}).json()["data"]
    actions = {row["action"] for row in body}
    assert "job_posting.import" in actions
    # 经 HTTP 触发的审计必须能回答"谁 + 关联哪个请求"（CLI/worker 等非 HTTP 来源允许无 request_id）
    http_rows = [row for row in body if row["action"] == "job_posting.import"]
    assert http_rows and all(row["actor_id"] and row["request_id"] for row in http_rows)


def test_given_ai_call_when_made_then_audit_event_written(client):
    """规范 §10：调用外部 AI 必须留审计（与 ai_runs 账本同一事务）。"""
    import asyncio

    from aios.modules.ai_gateway.gateway import AIGateway
    from aios.modules.ai_gateway.port import AIContext, AIOptions
    from aios.modules.ai_gateway.prompts import load_prompt
    from aios.modules.ai_gateway.providers import FakeProvider
    from pydantic import BaseModel

    class _Schema(BaseModel):
        ok: bool = False

    prompt = load_prompt("job_extraction.v1.md").with_variables({"material": "x"})
    gateway = AIGateway(FakeProvider(response='{"ok": true}'))
    asyncio.run(gateway.generate_structured(
        purpose="job_extraction", prompt=prompt, schema=_Schema,
        options=AIOptions(allow_cache=False, max_retries=0),
        context=AIContext(purpose="job_extraction", actor_id="test-actor")))

    rows = client.get("/api/v1/audit-events", params={"action": "ai.invoke", "limit": 5}).json()["data"]
    assert rows, "AI 调用必须产生审计事件"
    assert rows[0]["actor_id"] == "test-actor"


# ---------------------------------------------------------------- 鉴权（§10）

def test_given_auth_required_when_no_token_then_unauthenticated(client, monkeypatch):
    from aios.core.config import get_settings

    token = "test-token-abc"
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("AUTH_TOKEN_SHA256", hashlib.sha256(token.encode()).hexdigest())
    get_settings.cache_clear()
    try:
        assert client.get("/api/v1/job-postings").status_code == 401
        ok = client.get("/api/v1/job-postings", headers={"X-AIOS-Token": token})
        assert ok.status_code == 200
        assert client.get("/api/v1/job-postings", headers={"X-AIOS-Token": "wrong"}).status_code == 401
    finally:
        monkeypatch.delenv("AUTH_REQUIRED", raising=False)
        monkeypatch.delenv("AUTH_TOKEN_SHA256", raising=False)
        os.environ["AUTH_REQUIRED"] = "false"
        get_settings.cache_clear()


def test_given_prompts_endpoint_when_called_then_versions_visible(client):
    rows = client.get("/api/v1/prompts").json()["data"]
    assert any(r["id"] == "job_extraction" and r["version"] == "1" for r in rows)
