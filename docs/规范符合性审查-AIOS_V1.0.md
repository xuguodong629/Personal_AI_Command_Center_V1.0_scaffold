# 规范符合性审查：项目 vs AIOS Master Prompt V1.0

> 审查对象：`AIOS_Master_Prompt_V1.0.md`（687 行，工程基线）
> 被审对象：`Personal_AI_Command_Center_V1.0_scaffold`（当前仓库）
> 审查方式：逐节比对 + 仓库取证（文件树/行数/端点/依赖/配置存在性），不凭印象
> 审查日期：2026-09-22

---

## 实施进度（2026-09-22 更新）

已按规范**附录 A 初始实现顺序**落地第 1–4 步的可运行垂直切片（代码在 `backend/aios/**`，测试在 `tests/**`）：

| 附录 A 步骤 | 状态 | 落地内容 |
|---|---|---|
| 1 基础设施 | ✅ | 分域配置（`APP_/DB_/AUTH_/AI_/JIC_/OTEL_`）+ 启动校验、JSON 结构化日志（含 request_id/trace_id）、健康检查返回依赖状态与迁移版本、**Alembic 迁移**（2 个 revision）、单用户本地账户令牌骨架 |
| 2 Core | ✅ | 可枚举错误码 + 统一错误体、请求 ID 中间件、**审计事件**（不可变、与业务同事务）、**Outbox**、`scheduled_jobs`/`job_executions`（幂等键、退避、死信、孤儿回收）、常驻 worker |
| 3 JIC 最小闭环 | ✅ | 手动/雷达导入 → 规范化 → 去重（external_id → canonical_url → 指纹）→ 持久化 + 版本历史 → 事件 → **确定性匹配** → 职位 API + 用户状态 |
| 4 受审单一来源连接器 | ✅ | `job_sources` 策略表（域名/速率/预算/robots 检查时间/是否允许自动抓取与全文/保留期）+ 4 个 Spider 插件 + `SpiderManager` + `crawl_runs`/`crawl_items` + 403/429/验证码特征 → `blocked` |
| 5 搜索/提醒/匹配 | 部分 | 匹配已完成并可重算；`job_alerts` 表与创建/列表 API 已通；**提醒触发与投递未接** |
| 6 AI Gateway | 部分 | `AIService` 端口、路由/超时/重试/Schema 校验/缓存版本/`ai_runs` 账本/审计已通（真实 DeepSeek 调用验证）；**embedding 与多 Provider 切换策略待补** |
| 7 前端工作台/观测/备份 | 未做 | 前端仍是既有 React 界面（无作业卡片与 SSE）；OTel 未启用；备份与保留期未实现 |

**验收实测**：`ruff` 全绿；`pytest` **72 项通过**（unit 33 / integration 39）；既有 7 个 selfcheck 脚本全部 exit=0（无回归）；
12 个既有 `/api/*` 端点 200；`/api/v1/health` 返回 `status=ok`、迁移版本、outbox 待发布数；
真实雷达结果 31 条导入 JIC 后重复导入 31 条全部命中去重；禁用来源的采集请求被 `JOB_SOURCE_DISABLED` 拒绝。

**仍缺**（下一步优先级见本文第 3 节）：调度派发（`scheduled_jobs` → worker）、提醒投递、OTel 导出、备份与数据保留策略、
前端作业卡片与 SSE、`app/` 模块逐步迁移到 `aios/modules/*`。


## 0. 一句话结论

**功能与"确定性优先"的工程内核符合规范精神；但规范要求的四层架构、持久化数据模型、作业化、审计、可观测与安全基线基本没有落地。**
规范 §4 允许替换技术栈（换栈不算违规），但 §6/§9/§10/§13/§19/§21/§23 是**语义与安全要求，不允许替换**——这些是当前最大的合规缺口。

另需明确：**规范自己禁止逆向采集**（§2.2 非目标 2、§30.5、附录 B），因此本项目「不绕过登录墙 / 验证码 / 反爬」的既有立场与基线一致，无需调整。

---

## 1. 现状取证（可复核）

| 项 | 实测 |
|---|---|
| 后端 | `backend/app/` 12 个模块，**扁平结构**；`ai.py` 2929 行（路由+检索+抓取+提示词+报告解析混在一起） |
| 前端 | React 19 + Vite + **自研 CSS 变量**（2069 行），22 个 .tsx（4918 行）+ 16 个 .ts（1835 行） |
| 依赖 | 后端仅 `fastapi/uvicorn/pydantic/httpx/trafilatura/ddgs/mcp`；前端仅 `react/react-dom/lucide-react/react-markdown/remark-gfm` |
| 数据层 | **无数据库**。`data/` 下 13 个目录用 JSON/Markdown 文件存储；`data/database/` 只有一个 README |
| 队列/调度 | **无**。长任务在 API 进程内同步执行（一次雷达实测 60–120s） |
| 端点 | **46 个**，全部挂在 `/api/*`（无版本前缀）；响应为 `{ok:true,...}` 或裸对象 |
| 契约快照 | 根目录 `openapi.json`（93KB）与 `openapi_runtime.json` 均为当前 API 的契约快照（46 条路径）；但**全部无 `/api/v1` 前缀、响应 schema 为空 `{}`**（未声明 `response_model`） |
| 工程配置 | 无 `pyproject.toml` / `ruff` / `mypy` / `pytest.ini` / `.github/workflows` / `compose.yaml` / `.env.example` / `eslint.config.js` / `.prettierrc` / `tailwind.config.js` |
| 测试 | 7 个 `selfcheck_*.py`（`selfcheck_jobs.py` 62 项断言全通过）+ 11 个 `_tmp_probe_*.py` 诊断脚本；**不是 pytest 结构** |
| 关键词计数（`backend/app/*.py`） | `request_id` **0** ｜ `opentelemetry/trace_id` **0** ｜ AI 用量/成本账本 **0** ｜ `Idempotency` **0** ｜ `source_policy` **0** ｜ `SpiderManager/ParsedJobPosting` **0** ｜ SSRF/私网校验 **0** ｜ 保留期 `retention` **0** ｜ **`except Exception:` 31 处，其中 10 处下一行即 `pass/continue/return`（静默吞掉）**；裸 `except:` **0 处** ｜ 提示注入防护提示 **6 处** ✅ |
| 长任务 | `direct_radar`/`direct_bgcheck`/`direct_industry` 均 `await _gather_search(...)` 后继续调模型，**整个流程跑完才 return**（实测 HTTP 200 耗时 53–120s），未使用 `create_task`/`BackgroundTasks` |

---

## 2. 逐节符合性矩阵

判定口径：✅ 符合 ｜ ⚠️ 部分符合 ｜ ❌ 缺失 ｜ 🔁 需写偏离说明（ADR）

### 2.1 架构与分层

| 规范 | 要求 | 现状 | 判定 |
|---|---|---|---|
| §4 技术基线 | Next.js/TS/Tailwind、PG16、Redis+Celery、MinIO、OTel、pytest | React+Vite+自研 CSS、无 DB、无队列、无对象存储、无 OTel、脚本自检 | 🔁 换栈被 §4 允许，但需 ADR 说明 |
| §5 总体架构 | 请求路径 界面→API→应用服务→领域/仓储；**禁止 API 进程同步等待长时 AI/采集** | `direct/radar`、`bgcheck`、`industry` 全部同步跑完才返回（60–180s） | ❌ **明确违规**（必改） |
| §6.1 分层职责 | Presentation / Application / Domain / Infrastructure / Workers | 无分层：路由、编排、业务规则、HTTP 调用、提示词都在同一模块 | ❌ 缺失 |
| §6.2 依赖约束 | 内层不导外层；控制器不得直接查 ORM；跨模块走 contracts/事件 | 无 contracts/ports；`main.py` 与各模块直接持有文件读写与全局状态 | ❌ 缺失 |
| §6.2.6 AI Provider 规则 | Application 只依赖 `AIService` Port；Provider 支持热切换/超时/重试/限流/结构化输出校验；AI 调用记审计但不记完整 Prompt/PII/密钥 | Provider 是 pydantic 配置 + 模块内直接 httpx；**无 Port**；模型输出是自由 Markdown（正则解析），**无 Schema 校验** | ❌ 缺失 |
| §6.2.7 Spider Engine 规则 | `infrastructure/spiders/` 插件制 + `SpiderManager` + `discover/fetch/parse/health_check` + 只返回 DTO | 检索/抓取内联在 `ai.py::_gather_search`；无插件、无注册表 | ❌ 缺失 |
| §7 目录树 | `apps/{api,worker,web}` + `packages/{core,contracts,modules/*,integrations}` | `backend/app/*.py` + `frontend/src/**` | 🔁 目录差异（可 ADR；但分层语义必须补） |

### 2.2 接口、审计、可观测

| 规范 | 要求 | 现状 | 判定 |
|---|---|---|---|
| §9.1 API 约定 | `/api/v1`、复数 kebab-case、UUID、ISO8601 UTC、snake_case、列表分页+稳定排序+过滤白名单、写接口 `Idempotency-Key` | 46 端点无版本；资源名不统一；无分页规范；**幂等键 0 处** | ❌ 缺失 |
| §9.2/9.3 响应封装 | 成功 `{data,meta{request_id}}`；错误 `{error{code,message,details,request_id}}`；错误码可枚举 | `{ok:true/false, error:"中文串"}`；无 request_id；无错误码枚举 | ❌ 缺失 |
| §10 鉴权/授权 | 至少单用户本地账户；`actor_id`/`workspace_id` 一等字段；能力权限 read/write/run/approve/admin | **无鉴权**；无 actor/workspace 概念；CORS 放开 8 个来源（本地开发合理，但缺令牌） | ❌ 缺失 |
| §10 审计 | 下列动作必须生成**不可变审计事件**：改配置、启停来源、运行采集、导出、调用外部 AI、发通知、删除/归档、批准自动化 | 无 audit 实现；`data/decisions`、`data/review` 仅 README（设计意图有，落地无） | ❌ 缺失 |
| §13 事件/Outbox | 事务内 Outbox + 事件信封 + 消费者按 event_id 去重 | 无 | ❌ 缺失（无 DB 时无法实现，需与决策 1 绑定） |
| §22.1 日志 | JSON 结构化，含 `request_id`/`trace_id`/`service`/`level` | uvicorn 默认文本日志；`request_id` 0 处 | ❌ 缺失 |
| §22.2/22.3 指标与追踪 | 延迟/错误率/队列深度/来源健康/AI 成本等指标 + OTel 透传 + 可行动告警 | 无 | ❌ 缺失 |

### 2.3 Job Intelligence Center（功能上最大的结构性差距）

| 规范 | 要求 | 现状 | 判定 |
|---|---|---|---|
| §14 模块定位 | 独立可插拔 JIC：来源准入→标准化→去重→评分→检索→提醒 | 岗位雷达是**一次性"检索+LLM 报告"**；结果不落库、无来源注册、无变更历史 | ❌ 结构性缺失 |
| §14.1 来源准入 | 每来源 `source_policy`（域名/合法访问方式/允许路径/速率上限/robots 与条款检查时间/是否允许全文保存/保留期/启停）；未配置来源不得请求；401/403/验证码/429 立即停止并记 `blocked` | **已有**：robots.txt 检查、并发上限 6、登录墙按 URL 类型跳过、24h 缓存、错误诊断不混入材料 ✅；**缺**：来源注册表、per-source 速率/预算/保留期、"未配置不得请求"的强制闸门、`blocked` 状态机 | ⚠️ 方向正确，缺治理层 |
| §15 数据模型 | `job_sources/crawl_runs/crawl_items/companies/job_postings(+versions)/skills/job_posting_skills/job_matches/job_user_states/job_alerts` | 全无。**但**雷达的"确定性岗位候选清单"已含 `岗位/公司/地区/薪资/来源平台/链接/JD/证据`——天然就是 `job_postings` 的字段雏形 | ❌ 缺失（有可复用雏形） |
| §16 采集流程 | Preflight→Fetch→Parse→Normalize→Validate→Deduplicate→Persist→Post-process；解析器只输出 DTO | 已有等价流水线（准入→检索→抓取→抽取候选→规则判定→分池），但**不持久化、无版本、无指纹去重**（去重只在单次请求内按 URL 做） | ⚠️ 流程对，缺持久化与去重键 |
| §17 JIC API | 11 个 `/api/v1/job-postings*`、`job-sources`、`crawl-runs`、`job-alerts` 端点 | 无 | ❌ 缺失 |
| §18 匹配 | 确定性优先（无 AI 可跑）+ 记录分项/理由/规则版本/模型版本/输入哈希 + 模型输出 Schema 校验 | **本项目最强项**：`jobs.py/risk.py/industry.py/signals.py` 是确定性规则层，且已写明"模型不得推翻规则层数值、规则层等级是下限"；`job_matches` 的分项与理由已存在于响应 `_score_parts/_score_reasons`；**缺**：持久化、版本号、模型输出 Schema 校验 | ⚠️ 部分（精神符合，治理缺） |
| §19 调度/队列 | `scheduled_jobs`/`job_executions`+幂等键、misfire 策略、队列分类、指数退避、死信、来源预算（分/时/日+最大翻页+连续失败+冷却） | 无调度器（手动触发）；无队列/死信；有 24h 缓存与"空路放宽重试" | ❌ 缺失 |
| §20 缓存 | 键带命名空间+版本（`aios:v1:...`）；AI 缓存含 Provider/Model/Prompt 版本/Schema 版本/输入哈希 | 有 sha1 键 + 24h TTL（检索/页面）→ 方向对；**键无命名空间/版本；AI 路径无 prompt 版本；无主动失效**（只靠 TTL） | ⚠️ 部分 |

### 2.4 AI、安全、前端、测试、工程

| 规范 | 要求 | 现状 | 判定 |
|---|---|---|---|
| §21 AI Provider 抽象 | 只依赖 `AIService` Port；能力显式声明（chat/structured_output/embedding/vision/tool_calling/streaming）；Gateway 负责路由/凭据/超时/限额/重试/流式/Schema 校验/内容安全/审计/成本/缓存/降级；每次写 `ai_runs` | 无 Port；无能力声明；**无 ai_runs 账本（0 处 token/cost 记录）**；无 per-purpose 路由（由用户手选 provider_id）；无 Schema 校验 | ❌ 缺失 |
| §21.3 提示词 | 版本化文件/DB 模板（ID/版本/用途/输入输出 Schema/风险/样例）；**禁止在代码字符串里拼长提示词**；网页文本视为不可信数据 | **反例**：`RADAR_SYSTEM`、`INDUSTRY_SYSTEM`、背调/面试提示词等数百行硬编码在 `ai.py`；提示注入防护提示有 6 处 ✅ | ❌ 必须外置 |
| §23 安全与隐私 | HTTPS+超时+域名允许列表+**SSRF 防护**；URL 导入校验协议/域名/DNS/私网；参数化 SQL；强密码哈希；CSRF；上传 MIME/大小校验；PII 分级；依赖漏洞扫描 | **SSRF 校验 0 处**：`_fetch_page_text` 可抓任意 http(s)（含内网/元数据地址）；`/api/system/open-url` 只校验 scheme；无鉴权故无 CSRF 问题；无上传校验；无依赖扫描 | ❌ 缺失（SSRF 最急） |
| §24 前端 UX | 长任务立即返回作业卡片 + SSE/轮询；职位页显示来源/原始链接/抓取时间/最近更新/匹配理由/可信度；外部动作先展示范围与确认；AI 内容标注；无障碍 WCAG AA 基线 | 已有：加载态、toast、机会池显示链接/岗位评分/扣分原因 ✅；**缺**：作业状态模型（同步等待）、抓取时间/可信度字段、无障碍审计 | ⚠️ 部分 |
| §25 测试 | pytest 分层（unit/integration/contract/e2e/security）；必测场景（去重/解析器含提示注入/来源策略 403·429·验证码/作业幂等/AI 失败降级/跨 workspace 越权）；**修复缺陷必须附复现测试**；命名规范 | 7 个 selfcheck（62 项断言）**已满足"缺陷附复现测试"**（本轮每次修 bug 都补了断言）✅；**缺** pytest 结构、契约测试、越权测试（无鉴权）、幂等测试 | ⚠️ 部分 |
| §26 代码质量 | 类型标注/文档字符串/函数≤50 行/无裸 except/不硬编码 URL·密钥·模型名·阈值/CI 全绿 | 类型标注 ✅ 文档字符串 ✅；`ai.py` 2929 行、多个超长函数；**`except Exception:` 31 处中 10 处静默吞掉**（裸 `except:` 0 处，这点合规）；阈值硬编码（74/80/60 分、JD<24 字、单站 8 页、抓取 18 页）；无 lint/CI | ⚠️ 部分（违规项明确） |
| §27 CI/CD | 每次 MR 跑格式化/静态检查/类型检查/单测/集成/契约/漏洞扫描/构建；受保护分支 | 无 CI | ❌ 缺失 |
| §28 本地开发 | 一条命令或 Compose 起 API+Worker+PG+Redis+存储+观测；样例数据虚构 | 有 `启动.bat`/`启动桌面版.bat`（单进程，符合"一键"精神）；无 Compose/Worker/PG | 🔁 需 ADR |
| §29 数据生命周期 | 职位记录归档后 24 个月、原始页 7–30 天、错误证据 30–90 天、审计≥12 个月、AI 输入不保存；加密备份+恢复演练+RPO/RTO | 无保留策略（仅缓存 24h TTL）；无备份 | ❌ 缺失 |
| §30 生成规则 | 最小化改动、垂直切片、禁止伪造测试/来源许可/调用成功 | 本轮实践符合（未重写既有模块、改动最小、如实报告失败）✅ | ✅ |

---

## 3. 必须优先处理的 5 项（按 违规严重度 × 修复成本 排序）

| # | 目标 | 为什么必须做 | 最小改动方案（不重写） |
|---|---|---|---|
| 1 | **长任务作业化**（§5） | 规范**明令禁止** API 进程同步等待长时 AI/采集；当前雷达同步 60–120s，桌面端会"卡死"观感 | 加 `POST /api/v1/jobs` 建作业 → 后台执行（进程内 `asyncio.create_task` + 作业表 JSONL/SQLite）→ `GET /api/v1/jobs/{id}` 查状态 → 前端轮询。先只包雷达/背调/行业三条长任务 |
| 2 | **审计事件**（§10） | 验收清单与 §10 都要求；成本极低、收益立竿见影 | 新增 `audit.py`：append-only `data/audit/YYYY-MM.jsonl`，字段 actor/action/resource_type/resource_id/before-after 摘要/request_id/时间/结果；在改配置、跑采集、导出、AI 调用、删除归档处各加一次调用 |
| 3 | **SSRF + 最小鉴权**（§23/§10） | SSRF 是当前**唯一可直接被利用**的安全缺口；鉴权是 §10 硬要求 | 抓取与 URL 导入前校验：仅 http(s)、解析 DNS、拒绝私网/回环/链路本地/元数据地址、域名允许列表；加可选本地令牌（`X-AIOS-Token`，由设置页生成，默认仅监听 127.0.0.1 时关闭） |
| 4 | **API v1 + 统一封装 + request_id**（§9/§22） | 契约与错误语义是后续所有工作的地基；越晚改代价越大 | 用 `APIRouter(prefix="/api/v1")` 挂同一批路由（`/api/*` 保留为别名）；加 `RequestIdMiddleware` + 全局异常处理器，输出 `{data,meta}` / `{error{code,...}}`；给所有端点补 `response_model` |
| 5 | **提示词外置 + AI 账本**（§21） | §21.3 明确禁止代码内长提示词；无账本则无法回答"花了多少钱/为什么这次结果不同" | 提示词迁到 `backend/prompts/<name>.v1.md`（带 YAML front-matter：id/version/purpose/input_schema/output_schema）；加 `ai_runs.jsonl` 记 provider/model/purpose/tokens/cost/输入哈希/prompt 版本；AI 缓存键并入 prompt+schema 版本 |

---

## 4. 需要写 ADR 的 4 处"有意偏离"（规范允许换栈，但必须留痕）

| # | 偏离 | 建议 ADR 结论 |
|---|---|---|
| 1 | 前端 **React+Vite+自研 CSS** 而非 Next.js+Tailwind | 接受。理由：Tauri 桌面壳 + 无 SEO/SSR 需求；自研 CSS 变量体系已成型（2069 行）。**代价**：无 BFF，前端直连 API 并承担契约适配 |
| 2 | **无 PG/Redis/Celery**，文件即事实源 | 需决策（见第 5 节）。若保持文件优先：用 SQLite 作为"可重建索引"满足 §15/§12 的可查询性；若上 PG：用 Docker Compose（Docker 未装需先装） |
| 3 | **无 Workers 进程** | 不引入 Celery，改用"进程内后台任务 + 作业表 + 状态查询"满足 §5 的语义（立即返回作业卡片、可重试、可观测）——需 ADR 声明这是对 §4 的替换实现 |
| 4 | 目录结构 `backend/app` 而非 `apps/api + packages/modules` | 可选。若采纳第 5 节决策 1 的"分阶段"，建议**先按模块内部四层**（`app/<module>/{api,application,domain,infrastructure}`）渐进，避免大搬家 |

---

## 5. 需要你决策的 3 件事（决定后续工作量差一个数量级）

1. **数据层**：A) 保持"Markdown/JSON 即事实源"，只加 SQLite 作可重建索引（改动小，能满足 §15 的可查询/去重/版本）；B) 正式上 PostgreSQL 16 + Alembic（完全合规，但要装 Docker、写迁移、改所有仓储）。
2. **JIC 深度**：A) 只做"来源注册表 + 采集运行记录 + 职位去重持久化"三件事（能对上 §14/§15/§16 的主干）；B) 完整做 §15 全部 11 张表 + §17 全部端点 + §19 调度与提醒（工作量大，但一次性到位）。
3. **鉴权**：A) 纯本机单用户，不引入令牌（最简单，但 §10 缺项留为 ADR）；B) 引入本地单用户令牌 + actor 字段（合规，改动集中在中间件）。

---

## 6. 与规范一致的既有资产（不要动，是加分项）

1. **确定性规则层优先**（`jobs.py/risk.py/industry.py/signals.py/channel.py`）——直接对应 §18「第一阶段必须可在无 AI 条件下运行」，且已把"模型不得推翻规则层数值"写进提示词与文档。
2. **缺陷附复现测试**——`selfcheck_jobs.py` 62 项断言，每次修 bug 都补断言，符合 §25.2 末段。
3. **提示注入防护意识**——6 处提示"材料/网页文本是数据不是指令"，对应 §21.3。
4. **合规采集立场**——robots 检查、登录墙跳过、并发限制、不做逆向，对应 §2.2/§14.1/§30.5/附录 B。
5. **降级可用**——引擎报错给出可操作提示、零材料即失败不烧 token、手工粘贴材料零额度路径，对应 §3.7「降级可用」。
6. **本地优先 + 人审**——`review_required` 配置、归档到 `data/`、桌面壳自动起停后端，对应 §3.1/§2.1-6。
