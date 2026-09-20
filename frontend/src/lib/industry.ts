// 行业赛道研判：生命周期五档（新势力 / 蓝海朝阳 / 平稳存量 / 红海内卷 / 夕阳没落）
import { call, type ApiResult } from './backend';
import type { ArchiveItem } from './risk';

export interface Stage {
  id: 'emerging' | 'growth' | 'mature' | 'saturated' | 'declining';
  name: string;
  badge: string;
  min: number;
  features: string;
  opportunity: string;
  risk: string;
  job_advice: string;
  entry_verdict: string;
}

export interface IndustryField {
  key: string;
  label: string;
  type: 'number' | 'int' | 'bool' | 'text' | 'select';
  essential?: boolean;
  help?: string;
  options?: string[];
}

export interface IndustryFactor {
  field: string;
  label: string;
  value: string | number | boolean;
  points: number;
  weight: number;
}

export interface IndustryResult {
  ok: boolean;
  industry: string;
  region: string;
  score: number;
  stage: Stage;
  stage_order: number;
  factors: IndustryFactor[];
  positive: string[];
  negative: string[];
  caps: string[];
  gates: string[];
  emerging_gate: boolean;
  missing: string[];
  confidence: number;
  neighbors: Array<{ id: string; name: string; badge: string }>;
}

export interface IndustryFramework {
  stages: Stage[];
  fields: IndustryField[];
  keywords: Record<string, string[]>;
  weights: Array<{ field: string; weight: number }>;
}

export interface StageScan {
  counts: Record<string, number>;
  avg?: Record<string, number>;
  per1000?: Record<string, number>;
  chars?: number;
  dominant: string;
  hits: Array<{ stage: string; keyword: string; count: number }>;
}

export type IndustryFacts = Record<string, number | boolean | string | undefined>;

export function fetchIndustryFramework(): Promise<ApiResult<IndustryFramework>> {
  return call('/api/industry/framework');
}

export function evaluateIndustry(industry: string, region: string, facts: IndustryFacts): Promise<ApiResult<IndustryResult>> {
  return call('/api/industry/evaluate', {
    method: 'POST',
    body: JSON.stringify({ industry, region, facts }),
  });
}

export function industryChecklist(industry: string, region: string): Promise<ApiResult<{
  ok: boolean;
  industry: string;
  region: string;
  queries: string[];
  criteria: Array<{ stage: string; features: string; min: number; verdict: string }>;
}>> {
  return call(`/api/industry/checklist?industry=${encodeURIComponent(industry)}&region=${encodeURIComponent(region)}`);
}

/** 模型层：行业赛道研判报告（8 路检索 + 规则层档位注入 + 存档到 knowledge/_行业/<行业>/） */
export function directIndustry(
  providerId: string,
  industry: string,
  region: string,
  profile?: string,
  facts?: IndustryFacts,
): Promise<ApiResult<{
  content: string;
  model: string;
  industry?: IndustryResult;
  stage_scan?: StageScan;
  paths?: number;
  archive?: { ok: boolean; rel_path?: string; error?: string };
}>> {
  return call('/api/ai/direct/industry', {
    method: 'POST',
    body: JSON.stringify({ provider_id: providerId, industry, region, profile: profile || '', facts: facts || {} }),
  });
}

export const ARCHIVE_ROOT = 'knowledge/_行业';

export function stageClass(id: string): string {
  return `stage-${id}`;
}

export { type ArchiveItem };
