// 风控体检（公司背调升级）：18 项风险维度 + 本地规则判定 + 核查清单 + 报告存档
import { call, type ApiResult } from './backend';

export type Severity = 'veto' | 'high' | 'medium' | 'low' | 'info';

export interface RiskDimension {
  id: string;
  name: string;
  weight: string;
  key_questions: string[];
  search_queries: string[];
  verify: string;
}

export type FieldType = 'number' | 'int' | 'bool' | 'text' | 'select';

export interface FactsField {
  key: string;
  label: string;
  type: FieldType;
  group: string;
  essential?: boolean;
  help?: string;
  options?: string[];
}

export interface Portal {
  name: string;
  url: string;
  use: string;
}

export interface RiskMeta {
  dimensions: RiskDimension[];
  fields: FactsField[];
  groups: string[];
  portals: Portal[];
  severity_label: Record<Severity, string>;
}

export interface RiskFinding {
  id: string;
  dimension: string;
  severity: Severity;
  severity_label: string;
  title: string;
  detail: string;
  verify: string;
  advice: string;
}

export interface RiskResult {
  ok: boolean;
  company: string;
  score: number;
  level: '绿' | '黄' | '橙' | '红';
  level_hint: string;
  veto: boolean;
  counts: Record<Severity, number>;
  findings: RiskFinding[];
  confidence: number;
  missing: string[];
  years: number | null;
}

export interface ChecklistItem {
  id: string;
  name: string;
  weight: string;
  key_questions: string[];
  queries: string[];
  verify: string;
}

export interface ArchiveItem {
  company: string;
  file: string;
  title: string;
  saved_at: string;
  kind: string;
  risk: string;
  size: number;
  rel_path: string;
  mtime: number;
}

/** 事实值：数字 / 布尔 / 文本（未填为 undefined） */
export type FactsValue = number | boolean | string | undefined;
export type Facts = Record<string, FactsValue>;

export function fetchRiskMeta(): Promise<ApiResult<RiskMeta>> {
  return call('/api/risk/dimensions');
}

/** 本地规则层判定：同输入同输出，不调用模型 */
export function evaluateRisk(facts: Facts & { company_name?: string }): Promise<ApiResult<RiskResult>> {
  return call('/api/risk/evaluate', { method: 'POST', body: JSON.stringify(facts) });
}

/** 核查清单：每个维度的检索关键词 + 官方查询入口 */
export function fetchChecklist(company: string, top = 18): Promise<ApiResult<{ ok: boolean; company: string; items: ChecklistItem[]; portals: Portal[] }>> {
  return call(`/api/risk/checklist?company=${encodeURIComponent(company)}&top=${top}`);
}

/** 报告存档（默认 data/intelligence/<公司>/；行业研判用 knowledge/_行业） */
export function listReports(company = '', limit = 60, root = 'intelligence'): Promise<ApiResult<{ ok: boolean; items: ArchiveItem[]; dir: string }>> {
  return call(`/api/archive/reports?company=${encodeURIComponent(company)}&limit=${limit}&root=${encodeURIComponent(root)}`);
}

export function readReport(company: string, file: string, root = 'intelligence'): Promise<ApiResult<{ ok: boolean; file: string; content: string }>> {
  return call(`/api/archive/reports/read?company=${encodeURIComponent(company)}&file=${encodeURIComponent(file)}&root=${encodeURIComponent(root)}`);
}

export function deleteReport(company: string, file: string, root = 'intelligence'): Promise<ApiResult<{ ok: boolean; deleted: string }>> {
  return call(`/api/archive/reports?company=${encodeURIComponent(company)}&file=${encodeURIComponent(file)}&root=${encodeURIComponent(root)}`, { method: 'DELETE' });
}

/** 把事实按字段类型清洗成后端可校验的 JSON */
export function cleanFacts(fields: FactsField[], raw: Facts, company: string): Facts & { company_name: string } {
  const out: Facts & { company_name: string } = { company_name: company };
  for (const f of fields) {
    const v = raw[f.key];
    if (v === undefined || v === '' || v === null) continue;
    if (f.type === 'number' || f.type === 'int') {
      const n = Number(v);
      if (!Number.isNaN(n)) out[f.key] = f.type === 'int' ? Math.round(n) : n;
    } else if (f.type === 'bool') {
      if (v === true || v === 'true') out[f.key] = true;
      else if (v === false || v === 'false') out[f.key] = false;
    } else {
      out[f.key] = String(v);
    }
  }
  return out;
}

/** 风险等级 → CSS 修饰类 */
export function levelClass(level: string): string {
  return level === '绿' ? 'lv-green' : level === '黄' ? 'lv-yellow' : level === '橙' ? 'lv-orange' : 'lv-red';
}

export const SEVERITY_ORDER: Severity[] = ['veto', 'high', 'medium', 'low', 'info'];
