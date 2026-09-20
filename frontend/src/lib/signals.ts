// 信号扫描（岗位雷达 / 背调共用）：风险关键词 / 扩张利好 / 刷量线索 / 政策产业检索路
import { call, type ApiResult } from './backend';

export type SignalSeverity = 'veto' | 'high' | 'medium' | 'low';

export interface RiskSignal {
  keyword: string;
  count: number;
  dimension: string;
  severity: SignalSeverity;
  meaning: string;
  snippet: string;
}

export interface GrowthSignal {
  keyword: string;
  count: number;
  type: string;
  strength: string;
  snippet: string;
}

export interface VolumeSignal {
  keyword: string;
  count: number;
  signal: string;
  strength: string;
  snippet: string;
}

export interface VolumeRule {
  signal: string;
  subject: string;
  count: number;
  detail: string;
}

export interface Signals {
  risk: RiskSignal[];
  growth: GrowthSignal[];
  volume: VolumeSignal[];
  volume_rules: VolumeRule[];
  policy_queries?: string[];
  summary?: {
    risk_hits: number;
    risk_veto: number;
    risk_high: number;
    growth_hits: number;
    volume_hits?: number;
    volume_rules?: number;
    paths?: number;
    fetch?: { new: number; cached: number; blocked: number };
  };
}

export interface LexiconMeta {
  risk: { count: number; items: Array<{ keyword: string; dimension: string; severity: string; meaning: string }> };
  growth: { count: number; items: Array<{ keyword: string; type: string; strength: string; meaning: string }> };
  volume: { count: number; items: Array<{ keyword: string; signal: string; strength: string }> };
}

export function fetchLexicon(): Promise<ApiResult<LexiconMeta>> {
  return call('/api/signals/lexicon');
}

/** 对任意文本（粘贴的材料）做信号扫描 */
export function scanText(text: string): Promise<ApiResult<Signals & { summary: NonNullable<Signals['summary']> }>> {
  return call('/api/signals/scan', { method: 'POST', body: JSON.stringify({ text }) });
}

export const SEVERITY_ORDER: SignalSeverity[] = ['veto', 'high', 'medium', 'low'];

export const SEVERITY_LABEL: Record<SignalSeverity, string> = {
  veto: '一票否决',
  high: '高风险',
  medium: '关注',
  low: '提示',
};

/** 标题级别：把 severity 映射到已有风险样式类 */
export function severityClass(s: string): string {
  return `sev-${s}`;
}

export function isEmptySignals(s?: Signals | null): boolean {
  if (!s) return true;
  return (
    (s.risk?.length ?? 0) === 0 &&
    (s.growth?.length ?? 0) === 0 &&
    (s.volume?.length ?? 0) === 0 &&
    (s.volume_rules?.length ?? 0) === 0
  );
}
