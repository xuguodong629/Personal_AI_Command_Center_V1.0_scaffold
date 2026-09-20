// Dify 工作流 API 客户端（本地自部署 Docker）
// 用法：三个工作流在 Dify 里发布为 API 后，把 API 密钥填到页面设置里。

export interface DifyConfig {
  baseUrl: string;      // 例如 http://localhost （不要带 /v1）
  radarKey: string;     // 岗位雷达 API 密钥 sk-xxx
  bgKey: string;        // 公司背调 API 密钥 sk-xxx
  resumeKey: string;    // AI猎头中枢 API 密钥 sk-xxx
}

const STORAGE_KEY = 'job-center-dify-config';

export function loadConfig(): DifyConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as DifyConfig;
  } catch { /* ignore */ }
  return { baseUrl: 'http://localhost', radarKey: '', bgKey: '', resumeKey: '' };
}

export function saveConfig(cfg: DifyConfig) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
}

export interface RunResult {
  ok: boolean;
  outputs: Record<string, unknown>;
  error?: string;
  /** 完整的原始响应，供调试 */
  raw?: unknown;
  /** 本次执行耗时（毫秒） */
  elapsedMs?: number;
}

/** 输出里是否有实际内容（非 null / 空字符串） */
function hasContent(outputs: Record<string, unknown>): boolean {
  return Object.values(outputs).some(v => v !== null && v !== undefined && v !== '');
}

/** 把 Dify / 模型供应商的常见报错翻译成可操作的中文提示 */
function friendlyError(msg: string): string | null {
  if (/402|Insufficient Balance/i.test(msg)) {
    return '模型供应商账户余额不足（DeepSeek 返回 402 Insufficient Balance）。请到 platform.deepseek.com 充值后重试；也可以在 Dify 中把分类/摘要等轻量节点切换到本地 Ollama 模型（Qwen3.5-4B）以节省费用。';
  }
  if (/Authentication Fails|Unauthorized|invalid.{0,20}api.{0,20}key/i.test(msg)) {
    return '模型供应商拒绝了调用（API Key 无效或已被删除）。请到 Dify「设置 → 模型供应商」检查对应 Key。';
  }
  if (/timeout|timed?\s*out/i.test(msg)) {
    return '模型调用超时。可在 Dify 中调大节点超时设置，或降低并行路数后重试。';
  }
  return null;
}

/**
 * 调用 Dify 工作流（blocking 模式），并对各类异常给出可读诊断。
 * @param baseUrl Dify 地址（不含 /v1）
 * @param apiKey  该工作流的 API 密钥
 * @param inputs  工作流输入变量（必须与 Dify「开始」节点的变量名完全一致，
 *                Dify 会静默忽略名字对不上的输入，导致空跑）
 */
export async function runWorkflow(
  baseUrl: string,
  apiKey: string,
  inputs: Record<string, string | number>,
): Promise<RunResult> {
  if (!apiKey) return { ok: false, outputs: {}, error: '缺少 API 密钥，请在设置中填写。' };
  const url = `${baseUrl.replace(/\/+$/, '')}/v1/workflows/run`;
  const started = Date.now();
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ inputs, response_mode: 'blocking', user: 'job-center' }),
    });
    const text = await res.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      return {
        ok: false, outputs: {},
        error: `返回的不是 JSON（HTTP ${res.status}），地址可能不对：${text.slice(0, 160)}`,
        raw: text.slice(0, 2000),
      };
    }
    if (!res.ok) {
      const d = data as { message?: string; error?: string } | null;
      const msg = d?.message || d?.error || `HTTP ${res.status}`;
      return { ok: false, outputs: {}, error: `HTTP ${res.status}：${msg}`, raw: data };
    }

    const elapsedMs = Date.now() - started;
    // 标准响应：{ data: { status, outputs, error, workflow_run_id, ... } }
    const d = data as {
      data?: { status?: string; outputs?: Record<string, unknown>; error?: string | null };
      outputs?: Record<string, unknown>;
    } | null;
    const wf = d?.data;
    const outputs = wf?.outputs ?? d?.outputs ?? {};

    if (wf?.status && wf.status !== 'succeeded') {
      const friendly = friendlyError(wf.error ?? '');
      return {
        ok: false, outputs: {}, elapsedMs, raw: data,
        error: friendly ?? `工作流执行未成功（status=${wf.status}）${wf.error ? `：${wf.error.slice(0, 300)}` : ''}。可在 Dify 日志中查看该次运行详情。`,
      };
    }
    if (!hasContent(outputs)) {
      return {
        ok: false, outputs: {}, elapsedMs, raw: data,
        error: `执行完成但输出为空。请检查 Dify 工作流：①「结束」节点是否配置了输出变量（期望如 opportunity_pool / report / high_match_report），当前输出键：${
          Object.keys(outputs).join('、') || '（无）'
        }；②「开始」节点变量名是否与本页发送的一致（名字对不上的输入会被 Dify 静默丢弃）；③对应节点是否真的生成了内容。`,
      };
    }
    return { ok: true, outputs, elapsedMs, raw: data };
  } catch (e) {
    return {
      ok: false, outputs: {},
      error: `网络错误：${(e as Error).message}（请确认 Dify 已启动且地址正确）`,
    };
  }
}

export interface TestResult {
  ok: boolean;
  msg: string;
}

/**
 * 连接测试：GET /v1/parameters 校验 Key 并读取应用「开始」节点的输入变量名，
 * 用于排查「变量名不一致导致 Dify 静默丢弃输入」的问题。
 */
export async function testApp(baseUrl: string, apiKey: string): Promise<TestResult> {
  const url = `${baseUrl.replace(/\/+$/, '')}/v1/parameters`;
  try {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${apiKey}` } });
    const text = await res.text();
    let data: unknown = null;
    try { data = text ? JSON.parse(text) : null; } catch { /* fallthrough */ }
    if (res.status === 401) return { ok: false, msg: 'API Key 无效或未授权（401）' };
    if (res.status === 403) return { ok: false, msg: '无权访问该应用（403），请确认 Key 属于对应工作流应用' };
    if (!res.ok) {
      const d = data as { message?: string } | null;
      return { ok: false, msg: `HTTP ${res.status}：${d?.message || '连接失败'}` };
    }
    // user_input_form 形如 [{ "text-input": { variable, label, ... } }, ...]
    const form = (data as { user_input_form?: Array<Record<string, { variable?: string }>> } | null)?.user_input_form;
    const vars = (form ?? [])
      .map(f => Object.values(f)[0]?.variable)
      .filter((v): v is string => Boolean(v));
    return {
      ok: true,
      msg: vars.length
        ? `连接成功 · 开始节点输入变量：${vars.join('、')}`
        : '连接成功（未读到输入变量，该应用可能是 Chatflow 或未配置开始节点）',
    };
  } catch (e) {
    return { ok: false, msg: `无法连接 ${baseUrl}（${(e as Error).message}）` };
  }
}

/** 按优先字段名取输出（跳过空值；工作流有多个 end 节点时，取指定字段） */
export function pickOutput(
  outputs: Record<string, unknown>,
  preferKeys: string[],
): string {
  for (const k of preferKeys) {
    const v = outputs[k];
    if (typeof v === 'string' && v.trim()) return v;
    if (v !== undefined && v !== null && typeof v !== 'string') return JSON.stringify(v, null, 2);
  }
  return firstText(outputs);
}

/** 把输出里的第一个非空字符串字段取出（工作流 end 节点通常输出一个字符串变量） */
export function firstText(outputs: Record<string, unknown>): string {
  for (const v of Object.values(outputs)) {
    if (typeof v === 'string' && v.trim()) return v;
  }
  return JSON.stringify(outputs, null, 2);
}
