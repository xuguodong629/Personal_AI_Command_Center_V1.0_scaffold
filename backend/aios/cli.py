"""AIOS CLI（规范 §7 scripts / §28 本地运行）：迁移、令牌、来源、作业与雷达结果导入。

用法（backend 目录）：
    python -m aios.cli migrate                # 建/升级数据库（Alembic）
    python -m aios.cli check                  # 配置自检 + 依赖状态
    python -m aios.cli issue-token            # 生成本地访问令牌（只打印哈希供 .env 使用）
    python -m aios.cli seed-sources           # 写入内置来源策略样例（默认禁用）
    python -m aios.cli import-radar <json>    # 把岗位雷达结果导入 JIC（去重后入库）
    python -m aios.cli jobs [--limit 10]      # 查看作业
    python -m aios.cli run-due                # 手动执行一批到期作业
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import re
import secrets
import sys
from pathlib import Path
from typing import Any

from aios.contracts import JobSourcePolicy, RadarCandidate
from aios.core.config import PROJECT_ROOT, get_settings
from aios.core.http import Actor
from aios.modules.jobs import handlers as _job_handlers  # noqa: F401 —— 注册作业处理器，CLI 也能看到类型列表

URL_IN_TEXT = re.compile(r"https?://[^\s｜|，；)）]+")
CANDIDATE_FIELDS = ("岗位", "公司", "地区", "薪资", "来源平台", "链接", "JD要点", "缺什么")


def _cmd_migrate(_: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config

    backend = PROJECT_ROOT / "backend"
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "migrations"))
    command.upgrade(cfg, "head")
    print(f"迁移完成：{get_settings().db.url}")
    return 0


def _cmd_check(_: argparse.Namespace) -> int:
    settings = get_settings()
    print(f"环境={settings.app.env} 服务={settings.otel.service_name}")
    print(f"数据库={settings.db.url}")
    warnings = settings.validate()
    from aios.modules.jic.infrastructure.spiders import spider_manager
    from aios.modules.jobs.runner import registered_types

    print(f"已注册来源类型：{', '.join(spider_manager.registered_types())}")
    print(f"已注册作业类型：{', '.join(registered_types())}")
    from aios.modules.ai_gateway.prompts import list_prompts

    prompt_labels = ", ".join(f"{p['id']} v{p['version']}" for p in list_prompts())
    print(f"提示词：{prompt_labels}")
    for item in warnings:
        print(f"  [warn] {item}")
    return 0


def _cmd_issue_token(args: argparse.Namespace) -> int:
    token = args.token or secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    print("本地访问令牌（只显示一次，请自行保存）：")
    print(f"  {token}")
    print("把下面两行写入 .env：")
    print("  AUTH_REQUIRED=true")
    print(f"  AUTH_TOKEN_SHA256={digest}")
    print("请求时带 header： X-AIOS-Token: <令牌>")
    return 0


def _cmd_seed_sources(_: argparse.Namespace) -> int:
    """写入来源策略样例（规范 §14.1）：默认 disabled，需人工审查后启用。"""
    from aios.core.db import session_scope
    from aios.modules.jic.application import JICService

    seeds = [
        ("河南公共招聘网", "https://www.hn91w.gov.cn", "public_html"),
        ("海尔官方社招", "https://maker.haier.net", "official_career"),
        ("美的官方社招", "https://recruit.midea.com", "official_career"),
    ]
    created = 0
    with session_scope() as session:
        service = JICService(session, Actor(actor_id="cli", workspace_id="local-workspace"))
        for name, base_url, source_type in seeds:
            if service.sources.get_by_name(name) is not None:
                print(f"  已存在，跳过：{name}")
                continue
            domain = re.sub(r"^https?://", "", base_url).split("/")[0]
            policy = JobSourcePolicy(domain=domain, access_method=source_type if source_type != "public_html"
                                     else "public_html", allow_auto_crawl=False, allow_fulltext=False,
                                     note="样例策略：需人工核对 robots.txt 与使用条款后启用")
            service.create_source(name=name, base_url=base_url, source_type=source_type,
                                  policy=policy, status="disabled")
            created += 1
            print(f"  已创建（disabled）：{name}")
    print(f"完成：新增 {created} 个来源。启用前请先核对 robots.txt 与站点条款。")
    return 0


def _radar_item_to_candidate(item: dict[str, Any]) -> RadarCandidate:
    """把岗位雷达的行（列名中文）映射成 JIC 导入 DTO。链接里的 `｜[1.7]` 引用尾巴会被剥掉。"""
    def cell(*names: str) -> str:
        for name in names:
            value = item.get(name)
            if value:
                return str(value).strip()
        return ""

    link = cell("链接", "link", "url")
    m = URL_IN_TEXT.search(link)
    return RadarCandidate(
        title=cell("岗位", "职位"),
        company_name=cell("公司"),
        location=cell("地区", "工作地点"),
        salary_text=cell("薪资"),
        platform=cell("来源平台", "平台"),
        url=m.group(0) if m else link,
        description=cell("JD要点", "JD 要点", "JD", "缺什么"),
        evidence=cell("证据") or "radar",
    )


def _cmd_import_radar(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path if not path.exists() else path
    if not path.exists():
        print(f"文件不存在：{path}")
        return 2
    data = json.loads(path.read_text("utf-8-sig"))
    items: list[dict[str, Any]] = []
    for group in ("pool", "pending_jobs"):
        block = data.get(group) or {}
        items.extend(block.get("items") or [])
    if not items:
        print("该文件里没有 pool / pending_jobs 条目（是否传了 radar 结果 JSON？）")
        return 1
    candidates = [_radar_item_to_candidate(x) for x in items]
    before = len(candidates)
    candidates = [c for c in candidates if c.title and (c.url or c.company_name)]
    print(f"读取 {before} 条，有效 {len(candidates)} 条 → 导入 JIC")

    from aios.core.db import session_scope
    from aios.modules.jic.application import JICService

    with session_scope() as session:
        service = JICService(session, Actor(actor_id="cli", workspace_id="local-workspace"))
        stats = service.import_candidates(candidates, source_key="radar",
                                          actor_note=f"file={path.name}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def _cmd_jobs(args: argparse.Namespace) -> int:
    from aios.core.db import session_scope
    from aios.modules.jobs.models import JobExecution

    with session_scope() as session:
        rows = (session.query(JobExecution)
                .order_by(JobExecution.queued_at.desc().nullslast())
                .limit(args.limit).all())
        if not rows:
            print("暂无作业")
        for row in rows:
            print(f"{row.id}  {row.job_type:<26} {row.status:<10} attempts={row.attempts} "
                  f"err={row.error_code or '-'}")
    return 0


def _cmd_run_due(args: argparse.Namespace) -> int:
    from aios.modules.jobs import runner

    done = asyncio.run(runner.run_once(limit=args.limit))
    print(f"已执行 {done} 个到期作业")
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    """用 AI 网关从材料文本抽取岗位（规范 §21）：提示词取版本化文件，输出必须过 Schema，调用记入账本。"""
    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在：{path}")
        return 2
    material = path.read_text("utf-8-sig")
    from aios.core.ids import new_trace_id
    from aios.core.logging import set_request_context
    from aios.modules.ai_gateway.gateway import AIGateway
    from aios.modules.ai_gateway.port import AIContext, AIOptions
    from aios.modules.ai_gateway.prompts import load_prompt
    from aios.modules.ai_gateway.schemas import PostingList

    set_request_context("cli", new_trace_id())
    prompt = load_prompt("job_extraction.v1.md").with_variables({"material": material[:20000]})
    context = AIContext(purpose="job_extraction", actor_id="cli", workspace_id="local-workspace",
                        prompt_id=prompt.id, prompt_version=prompt.version)
    try:
        result = asyncio.run(AIGateway().generate_structured(
            purpose="job_extraction", prompt=prompt, schema=PostingList,
            options=AIOptions(temperature=0, max_tokens=2000), context=context))
    except Exception as exc:  # noqa: BLE001 —— CLI 需要把失败原因完整呈现
        print(f"抽取失败：{type(exc).__name__}: {exc}")
        return 1
    postings = result.output.postings
    print(f"抽取到 {len(postings)} 条（provider={result.provider} model={result.model} "
          f"tokens={result.token_usage} latency={result.latency_ms}ms cache={result.cache_hit}）")
    for item in postings:
        print(f"  · {item.title} | {item.company_name or '材料未见'} | {item.location or '材料未见'} | "
              f"{item.salary_text or '材料未见'} | conf={item.confidence}")
    if args.import_to_jic and postings:
        candidates = [RadarCandidate(title=p.title, company_name=p.company_name, location=p.location,
                                     salary_text=p.salary_text, platform="AI抽取", url=p.url,
                                     description=p.description, evidence="ai_extract")
                      for p in postings]
        from aios.core.db import session_scope
        from aios.modules.jic.application import JICService

        with session_scope() as session:
            service = JICService(session, Actor(actor_id="cli", workspace_id="local-workspace"))
            stats = service.import_candidates(candidates, source_key="ai_extract",
                                              actor_note=f"file={path.name}")
        print("导入 JIC：" + json.dumps(stats, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aios", description="AIOS 运维 CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="建/升级数据库").set_defaults(func=_cmd_migrate)
    sub.add_parser("check", help="配置自检与注册点列表").set_defaults(func=_cmd_check)

    p_token = sub.add_parser("issue-token", help="生成本地访问令牌")
    p_token.add_argument("--token", default="", help="自定义令牌（默认随机）")
    p_token.set_defaults(func=_cmd_issue_token)

    sub.add_parser("seed-sources", help="写入来源策略样例（默认禁用）").set_defaults(func=_cmd_seed_sources)

    p_radar = sub.add_parser("import-radar", help="导入岗位雷达结果 JSON")
    p_radar.add_argument("path", help="radar 结果 JSON 路径（如 data/logs/radar-res-v2.json）")
    p_radar.set_defaults(func=_cmd_import_radar)

    p_jobs = sub.add_parser("jobs", help="查看作业")
    p_jobs.add_argument("--limit", type=int, default=10)
    p_jobs.set_defaults(func=_cmd_jobs)

    p_due = sub.add_parser("run-due", help="手动执行一批到期作业")
    p_due.add_argument("--limit", type=int, default=10)
    p_due.set_defaults(func=_cmd_run_due)

    p_ex = sub.add_parser("extract", help="用 AI 从材料文本抽取岗位（提示词版本化 + Schema 校验 + 账本）")
    p_ex.add_argument("path", help="材料文本文件路径（如 JD 文本或检索材料）")
    p_ex.add_argument("--import-to-jic", action="store_true", help="抽取后直接导入 JIC")
    p_ex.set_defaults(func=_cmd_extract)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK：把标准输出切成 UTF-8，避免中文/符号打印崩溃
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
