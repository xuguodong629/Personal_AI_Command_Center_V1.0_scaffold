// 扩展能力：MCP 服务器（成熟外部模块）+ Skills（技能指令包）
const BASE = localStorage.getItem('jc-backend-url') || 'http://127.0.0.1:8787';

export interface McpServer {
  id: string;
  name: string;
  transport: 'stdio' | 'http';
  command: string;
  args: string[];
  env: Record<string, string>;
  url: string;
  enabled: boolean;
  auto_approve: boolean;
  note: string;
  tool_count?: number | null;
}

export interface McpTool {
  full_name: string;
  server_id: string;
  tool: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface SkillSummary {
  name: string;
  title: string;
  description: string;
  chars: number;
  updated_at: number;
}

async function call<T>(path: string, init?: RequestInit): Promise<({ ok: true } & T) | { ok: false; error: string }> {
  try {
    const res = await fetch(`${BASE}${path}`, { headers: { 'Content-Type': 'application/json' }, ...init });
    const data = (await res.json().catch(() => null)) as Record<string, unknown> | null;
    if (!res.ok) return { ok: false, error: (data?.detail as string) || `HTTP ${res.status}` };
    return data as { ok: true } & T;
  } catch {
    return { ok: false, error: '无法连接本地后端（127.0.0.1:8787）' };
  }
}

/* ---------------- MCP ---------------- */

export function listServers() {
  return call<{ servers: McpServer[] }>('/api/mcp/servers');
}

export function saveServers(servers: McpServer[]) {
  return call<{ servers: McpServer[] }>('/api/mcp/servers', { method: 'POST', body: JSON.stringify({ servers }) });
}

export function deleteServer(id: string) {
  return call<Record<string, never>>(`/api/mcp/servers/${id}`, { method: 'DELETE' });
}

export function testServer(id: string) {
  return call<{ latency_ms: number; tools: Array<{ name: string; description: string }> }>(
    `/api/mcp/servers/${id}/test`,
    { method: 'POST' },
  );
}

export function listTools(refresh = false) {
  return call<{ tools: McpTool[]; errors: string[] }>(`/api/mcp/tools${refresh ? '?refresh=true' : ''}`);
}

export function callTool(serverId: string, tool: string, args: Record<string, unknown>) {
  return call<{ content: string; is_error?: boolean }>('/api/mcp/call', {
    method: 'POST',
    body: JSON.stringify({ server_id: serverId, tool, arguments: args }),
  });
}

/** 常用 MCP 服务器预设：一键添加（首次运行会联网下载包） */
export const MCP_PRESETS: Array<{ label: string; server: Omit<McpServer, 'id' | 'enabled' | 'auto_approve' | 'tool_count'> }> = [
  {
    label: '文件系统（读写字幕/报告/知识库）',
    server: { name: '文件系统', transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-filesystem', '.'], env: {}, url: '', note: '需把 args 最后的 "." 改成你要授权的目录' },
  },
  {
    label: '网页抓取 Fetch（转 Markdown）',
    server: { name: '网页抓取', transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-fetch'], env: {}, url: '', note: '' },
  },
  {
    label: 'SQLite（查询本地库）',
    server: { name: 'SQLite', transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-sqlite', './data/database/aios.db'], env: {}, url: '', note: '把路径改成你的 .db 文件' },
  },
  {
    label: 'Git（知识库版本管理）',
    server: { name: 'Git', transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-git', '--repository', '.'], env: {}, url: '', note: '把 "." 改成你的仓库目录' },
  },
  {
    label: '长期记忆 Memory（知识图谱）',
    server: { name: '记忆', transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-memory'], env: {}, url: '', note: '' },
  },
  {
    label: '结构化推理 Sequential Thinking',
    server: { name: '推理', transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-sequential-thinking'], env: {}, url: '', note: '' },
  },
  {
    label: '浏览器自动化 Playwright（可翻动态页）',
    server: { name: '浏览器', transport: 'stdio', command: 'npx', args: ['-y', '@playwright/mcp@latest'], env: {}, url: '', note: '首次会下载浏览器内核' },
  },
];

/* ---------------- Skills ---------------- */

export function listSkills() {
  return call<{ skills: SkillSummary[] }>('/api/skills');
}

export function getSkill(name: string) {
  return call<{ skill: { name: string; title: string; description: string; content: string; path: string } }>(
    `/api/skills/${encodeURIComponent(name)}`,
  );
}

export function saveSkill(name: string, content: string) {
  return call<{ skill: { name: string } }>('/api/skills', { method: 'POST', body: JSON.stringify({ name, content }) });
}

export function deleteSkill(name: string) {
  return call<Record<string, never>>(`/api/skills/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export function runSkill(name: string, providerId: string, input: string, context = '') {
  return call<{ content: string; model: string; skill: string }>(`/api/skills/${encodeURIComponent(name)}/run`, {
    method: 'POST',
    body: JSON.stringify({ provider_id: providerId, input, context }),
  });
}

export function importSkill(url: string, name = '') {
  return call<{ name: string; title: string }>('/api/skills/import', {
    method: 'POST',
    body: JSON.stringify({ url, name }),
  });
}

/* ---------------- 工具调用对话 ---------------- */

export interface ToolTraceItem {
  tool: string;
  server_id: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  result_preview: string;
}

export function chatWithTools(body: {
  provider_id: string;
  messages: Array<{ role: string; content: string }>;
  server_ids?: string[];
  max_rounds?: number;
  system?: string;
}) {
  return call<{ content: string; trace: ToolTraceItem[]; tool_errors: string[]; model: string }>('/api/ai/chat-tools', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}
