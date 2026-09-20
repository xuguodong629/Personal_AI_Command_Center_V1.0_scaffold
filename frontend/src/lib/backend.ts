// 本地 FastAPI 后端客户端（模型直连：供应商配置 / 连接测试 / 对话）

const BASE = localStorage.getItem('jc-backend-url') || 'http://127.0.0.1:8787';

export interface ModelProvider {
  id: string;
  name: string;
  base_url: string;
  api_key: string;
  model: string;
}

export type ApiResult<T> =
  | ({ ok: true } & T)
  | { ok: false; error: string };

export async function call<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const d = data as { detail?: unknown } | null;
      const detail = typeof d?.detail === 'string' ? d.detail : `HTTP ${res.status}`;
      return { ok: false, error: detail };
    }
    return data as ApiResult<T>;
  } catch {
    return {
      ok: false,
      error: '无法连接本地后端（127.0.0.1:8787）。请启动：cd backend && uvicorn app.main:app --port 8787',
    };
  }
}

export function fetchProviders(): Promise<ApiResult<{ providers: ModelProvider[] }>> {
  return call('/api/providers');
}

export function saveProviders(providers: ModelProvider[]): Promise<ApiResult<{ providers: ModelProvider[] }>> {
  return call('/api/providers', { method: 'POST', body: JSON.stringify({ providers }) });
}

export function testProvider(p: { base_url: string; api_key: string; model: string }): Promise<ApiResult<{ reply: string; latency_ms: number }>> {
  return call('/api/providers/test', { method: 'POST', body: JSON.stringify(p) });
}

export interface ChatMsg {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export function chat(providerId: string, messages: ChatMsg[]): Promise<ApiResult<{ content: string; model: string; latency_ms: number }>> {
  return call('/api/ai/chat', {
    method: 'POST',
    body: JSON.stringify({ provider_id: providerId, messages }),
  });
}

/** 联网搜索配置（直连模式的雷达 / 背调使用） */
export type SearchEngine = 'none' | 'zhipu' | 'tavily' | 'ddg' | 'searxng' | 'mcp' | 'serper' | 'brave' | 'bocha';

/** 搜索引擎清单（含额度提示，用于设置页下拉与自检） */
export const SEARCH_ENGINES: Array<{ id: SearchEngine; label: string; quota: string; needKey: boolean }> = [
  { id: 'none', label: '不启用', quota: '只用本地规则层，不联网', needKey: false },
  { id: 'ddg', label: 'DuckDuckGo（免 Key，实测国内可用）', quota: '免费无限，无需注册；质量中等', needKey: false },
  { id: 'searxng', label: '自建 SearXNG（本地聚合，完全免费）', quota: '需 Docker 自建；可聚合百度/必应', needKey: false },
  { id: 'mcp', label: 'MCP 检索工具（把任意 MCP 当引擎）', quota: '取决于所用 MCP（如 SearXNG/JobSpy/自定义）', needKey: false },
  { id: 'tavily', label: 'Tavily（召回最好）', quota: '免费 1000 次/月，用尽报 432', needKey: true },
  { id: 'zhipu', label: '智谱 GLM 搜索', quota: '按账户余额计费，余额不足报 429', needKey: true },
  { id: 'serper', label: 'Serper（Google 结果）', quota: '免费 2500 次（一次性）；实测网络可达', needKey: true },
  { id: 'brave', label: 'Brave Search', quota: '免费 2000 次/月；⚠️ 本机实测超时（需代理）', needKey: true },
  { id: 'bocha', label: '博查 Bocha（国内直连）', quota: '按量计费，国内可直连', needKey: true },
];

export type Fetcher = 'auto' | 'http' | 'crawl4ai';

export interface SearchConfig {
  engine: SearchEngine;
  api_key: string;
  /** 备用引擎：主引擎无结果/报错时自动切换 */
  fallback_engine: SearchEngine;
  fallback_api_key: string;
  /** engine=searxng 时：自建 SearXNG 地址 */
  searxng_url: string;
  /** engine=mcp 时：MCP 服务器 id / 工具名 / 查询参数名 */
  mcp_server_id: string;
  mcp_tool: string;
  mcp_query_arg: string;
  /** 时间范围：0=不限 / 1 / 7 / 30（天） */
  days: number;
  /** 每路检索条数 3–10 */
  max_results: number;
  /** 限定域名，逗号分隔（Tavily 原生；智谱用 site: 降级） */
  include_domains: string;
  /** 排除域名，逗号分隔 */
  exclude_domains: string;
  /** 排除词，逗号分隔（拼成查询负词） */
  exclude_keywords: string;
  /** 是否抓取公开页正文（补全 JD） */
  fetch_pages: boolean;
  /** 单次最多抓取页数 */
  fetch_limit: number;
  /** 抓取器：auto=有 crawl4ai 就用，否则轻量抓取 */
  fetcher: Fetcher;
  /** 跳过登录墙平台（BOSS直聘 / 领英等） */
  skip_login_walls: boolean;
}

export function fetchSearchConfig(): Promise<ApiResult<{ search: SearchConfig }>> {
  return call('/api/search');
}

export function saveSearchConfig(cfg: SearchConfig): Promise<ApiResult<{ search: SearchConfig }>> {
  return call('/api/search', { method: 'POST', body: JSON.stringify(cfg) });
}

export interface SearchTestResult {
  ok: boolean;
  engine: string;
  count?: number;
  latency_ms: number;
  error?: string;
  note?: string;
  samples?: Array<{ title: string; url: string }>;
}

/** 一键自检搜索引擎：直接告诉你「能搜到 / 额度用尽 / Key 无效 / 网络不通」 */
export function testSearch(engine?: string, apiKey?: string): Promise<ApiResult<SearchTestResult>> {
  return call('/api/search/test', { method: 'POST', body: JSON.stringify({ engine: engine || '', api_key: apiKey || '' }) });
}

/** 检索诊断（引擎为空的真正原因，前端直接展示，不再埋进报告里） */
export interface SearchDiagnostics {
  engine?: string;
  engine_configured?: string;
  switched?: boolean;
  paths?: number;
  per_query?: number;
  results?: number;
  empty_paths?: number;
  empty_queries?: string[];
  relaxed_used?: string[];
  errors?: string[];
  hint?: string;
  fetch_note?: string;
  cache_hits?: number;
  cache_miss?: number;
}

export interface RadarInputs {
  position_keywords: string;
  regions: string;
  industries: string;
  resume_summary: string;
  /** 候选人画像 + 优先级 + 底线 + 评分权重（评分依据） */
  profile?: string;
  /** 本次检索范围：all | job_boards | official | linkedin */
  scope?: string;
  /** 定向核查的目标企业（逗号分隔），雷达会为其生成专门查询 */
  target_companies?: string;
  /** 公司性质（可多选，逗号分隔）：world500|cn500|industry_leader|foreign|listed|state_owned|private|joint_venture */
  company_tier?: string;
  /** 月薪范围（元，0=不限） */
  salary_min?: number;
  salary_max?: number;
  /** 经验要求：any | 1-3 | 3-5 | 5-10 | 10+ */
  exp_years?: string;
  /** 公司规模：any | 0-19 | 20-99 | 100-499 | 500-999 | 1000-9999 | 10000+ */
  company_size?: string;
  /** 学历：any | 中专 | 高中 | 大专 | 本科 | 硕士 | 博士 */
  edu?: string;
  /** 发布时间：0=不限 / 1 / 3 / 7 / 30（天） */
  publish_days?: number;
  /** 职位类型：any | 全职 | 兼职 | 实习 */
  job_type?: string;
  /** 福利标签（逗号分隔）：五险一金 / 双休 / 年终奖… */
  welfare_tags?: string;
  /** 保障要求：any | wuxianyijin | wuxian */
  welfare?: string;
  /** 排除外包 / 派遣 / 中介 */
  no_outsourcing?: boolean;
  /** ① 公司风险联动：命中风险关键词直接标注、不给高推荐 */
  risk_scan?: boolean;
  /** ② 扩张利好：融资/上市/扩产/技术突破/中标 */
  growth_scan?: boolean;
  /** ③ 雇主口碑：看准/脉脉/知乎/投诉平台 */
  review_scan?: boolean;
  /** ④ 政策与产业：国家/地方规划、扶持目录、产业链上下游 */
  policy_scan?: boolean;
  /** 目标机会条数（10/20/30/50，上限 60） */
  want_count?: number;
  /** 每路检索条数（0=自动；1–20） */
  per_query?: number;
  /** 第几批（0=首批；「换一批」时 +1，用于轮换检索组合） */
  batch?: number;
  /** 已展示过的「公司·岗位」列表（换一批时排除，避免重复） */
  skip_seen?: string;
  /** 手工粘贴材料：填了就完全跳过搜索引擎（零额度也能分析） */
  manual_material?: string;
}

/** 机会池解析结果（用于「换一批」去重、条数统计与机会池面板渲染） */
export interface RadarPool {
  rows: number;
  want: number;
  batch: number;
  paths: number;
  per_query: number;
  seen: string[];
  keys: Array<{ post: string; company: string }>;
  /** 表一整行的结构化数据（列名 → 单元格），供 PoolBoard 渲染 */
  items?: Array<Record<string, string>>;
}

/** 直连模式：定制简历（纯 LLM） */
export function directResume(providerId: string, jobDescription: string, resumeText: string): Promise<ApiResult<{ content: string; model: string }>> {
  return call('/api/ai/direct/resume', {
    method: 'POST',
    body: JSON.stringify({ provider_id: providerId, job_description: jobDescription, resume_text: resumeText }),
  });
}

/** 直连模式：公司背调（多路搜索 + 汇总）；profile 为候选人底线（雇主风险核查透镜）
 * mode=full 16 章完整报告 / risk 只做风险体检；deepRisk 追加 10 路风控检索；facts 为手填工商事实（本地规则层判定） */
export function directBgcheck(
  providerId: string,
  companyName: string,
  profile?: string,
  opts?: { mode?: 'full' | 'risk'; deepRisk?: boolean; facts?: Record<string, unknown>; manualMaterial?: string },
): Promise<ApiResult<{ content: string; model: string; risk?: unknown; signals?: unknown; diagnostics?: unknown; archive?: { ok: boolean; rel_path?: string; error?: string } }>> {
  return call('/api/ai/direct/bgcheck', {
    method: 'POST',
    body: JSON.stringify({
      provider_id: providerId,
      company_name: companyName,
      profile: profile || '',
      mode: opts?.mode || 'full',
      deep_risk: opts?.deepRisk ?? true,
      facts: opts?.facts || {},
      manual_material: opts?.manualMaterial || '',
    }),
  });
}

/** 直连模式：岗位雷达（多路搜索 + 评估分档）；signals 为确定性词库命中，pool 为机会池条数统计 */
export function directRadar(
  providerId: string,
  inputs: RadarInputs,
): Promise<ApiResult<{ content: string; model: string; signals?: unknown; pool?: RadarPool }>> {
  return call('/api/ai/direct/radar', {
    method: 'POST',
    body: JSON.stringify({ provider_id: providerId, ...inputs }),
  });
}

/** 直连模式：目标企业触点地图（公开渠道联系人与触达路径，不含个人手机号） */
export function directContactMap(providerId: string, companyName: string, profile?: string): Promise<ApiResult<{ content: string; model: string }>> {
  return call('/api/ai/direct/contact-map', {
    method: 'POST',
    body: JSON.stringify({ provider_id: providerId, company_name: companyName, profile: profile || '' }),
  });
}

/** 用系统默认浏览器打开外部链接（桌面端避免应用窗口被导航走） */
export function openExternal(url: string): Promise<ApiResult<{ url: string }>> {
  return call('/api/system/open-url', { method: 'POST', body: JSON.stringify({ url }) });
}

/* ---------------- 模拟面试（P1 文字版） ---------------- */

export interface InterviewTurnBody {
  provider_id: string;
  stage: string;
  round_no: number;
  history: ChatMsg[];
  profile?: string;
  jd?: string;
  company?: string;
  role_persona?: string;
  user_answer?: string;
}

export interface InterviewTurnResult {
  reply: string;
  stage: string;
  round_no: number;
  finished: boolean;
  stage_label: string;
  progress: string;
}

/** 面试回合：出题 / 点评+下一题 */
export function interviewTurn(body: InterviewTurnBody): Promise<ApiResult<InterviewTurnResult>> {
  return call('/api/ai/interview', { method: 'POST', body: JSON.stringify(body) });
}

/** 面试复盘报告 */
export function interviewReview(body: {
  provider_id: string;
  history: ChatMsg[];
  profile?: string;
  jd?: string;
  company?: string;
  role_persona?: string;
}): Promise<ApiResult<{ content: string; model: string }>> {
  return call('/api/ai/interview/review', { method: 'POST', body: JSON.stringify(body) });
}

/** 深度分析模式：invest=投资视角 VC 五步 / screen=优秀企业筛选 6 步 */
export type DeepMode = 'invest' | 'screen';

/** 直连模式：深度分析（基于雷达机会池，按画像执行） */
export function directDeep(providerId: string, mode: DeepMode, radarResult: string, profile?: string): Promise<ApiResult<{ content: string; model: string }>> {
  return call('/api/ai/direct/deep', {
    method: 'POST',
    body: JSON.stringify({ provider_id: providerId, mode, radar_result: radarResult, profile: profile || '' }),
  });
}

/** 常见模型服务的正确预置参数（base_url 是最常见的出错点） */
export const PRESETS: Array<{ label: string; base_url: string; model: string }> = [
  { label: '智谱 GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4.5-air' },
  { label: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  { label: 'Ollama 本地（免费）', base_url: 'http://localhost:11434/v1', model: 'qwen3.5:4b' },
  { label: 'Moonshot Kimi', base_url: 'https://api.moonshot.cn/v1', model: 'kimi-k2-0905-preview' },
  { label: '阿里通义 Qwen', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  { label: '自定义（OpenAI 兼容）', base_url: '', model: '' },
];
