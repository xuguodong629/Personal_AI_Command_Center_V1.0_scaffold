// 机会池面板：把「表一」从 14 列 markdown 表格变成可读的卡片 / 紧凑表格
import type { RadarPool } from './backend';

/** 表一的一行（列名 → 单元格文本），另附后台挂上的评分 */
export type PoolItem = Record<string, string>;

export interface LevelInfo {
  /** 高 / 中 / 低 / 待核实 */
  level: string;
  /** 一句话级描述（去掉 ⚠️ 后的括号内容） */
  note: string;
  flags: string[];
  rank: number;      // 排序用：高=3 中=2 低=1 待核实=0
  tone: 'high' | 'mid' | 'low' | 'risk' | 'unknown';
}

const FLAG_RE = /⚠️\s*([^（(；;|]*)/g;

/** 解析「级」列：`中⚠️刷量`、`低⚠️公司风险`、`低（行业不符）`、`待核实（无 JD）` */
export function parseLevel(raw: string): LevelInfo {
  const s = (raw || '').trim();
  const level = /高/.test(s) ? '高' : /中/.test(s) ? '中' : /低/.test(s) ? '低' : '待核实';
  const flags: string[] = [];
  let m: RegExpExecArray | null;
  FLAG_RE.lastIndex = 0;
  while ((m = FLAG_RE.exec(s))) {
    const f = m[1].replace(/[（(].*$/, '').trim();
    if (f) flags.push(f);
  }
  const noteMatch = s.match(/[（(]([^）)]+)[）)]/);
  const note = flags.length ? flags.join('、') : noteMatch ? noteMatch[1] : '';
  const risk = flags.some(f => /风险|底线|一票否决|刷量|骗局/.test(f));
  const tone: LevelInfo['tone'] =
    level === '高' ? (risk ? 'risk' : 'high')
    : level === '中' ? (risk ? 'risk' : 'mid')
    : level === '低' ? (risk ? 'risk' : 'low')
    : 'unknown';
  return { level, note, flags, rank: level === '高' ? 3 : level === '中' ? 2 : level === '低' ? 1 : 0, tone };
}

/** 从「薪资」列里取出**月薪**中位数（元），用于排序；解析不到返回 -1。
 *  注意中文口径：JD 里「1.5-2万」通常指月薪；只有写「年薪/年包」时才按月折算。 */
export function salaryValue(raw: string): number {
  const s = raw || '';
  const kRange = s.match(/(\d+(?:\.\d+)?)\s*[-~—]\s*(\d+(?:\.\d+)?)\s*[kK]/);
  if (kRange) return ((Number(kRange[1]) + Number(kRange[2])) / 2) * 1000;
  const kOne = s.match(/(\d+(?:\.\d+)?)\s*[kK]/);
  if (kOne) return Number(kOne[1]) * 1000;
  const wRange = s.match(/(\d+(?:\.\d+)?)\s*[-~—]\s*(\d+(?:\.\d+)?)\s*万/);
  const wOne = s.match(/(\d+(?:\.\d+)?)\s*万/);
  const wan = wRange ? (Number(wRange[1]) + Number(wRange[2])) / 2 : wOne ? Number(wOne[1]) : 0;
  if (wan > 0) {
    const annual = /年薪|年包|每年/.test(s);   // 年薪 → 折月；否则按月薪算
    return annual ? (wan * 10000) / 12 : wan * 10000;
  }
  return -1;
}

export function scoreValue(it: PoolItem): number {
  const cleaned = (it._score || '').replace(/[^\d.]/g, '');
  if (!cleaned) return -1;                     // 「无法计算」「材料未覆盖」等 → -1，不能当成 0 分
  const n = Number(cleaned);
  return Number.isNaN(n) ? -1 : n;
}

export function field(it: PoolItem, ...names: string[]): string {
  for (const n of names) {
    const hit = Object.keys(it).find(k => k.includes(n));
    if (hit && it[hit]) return it[hit];
  }
  return '';
}

/** 把一行拼成可读的公司/岗位组合（公司名可能带「/」分裂） */
export function cleanCompany(it: PoolItem): string {
  return field(it, '公司').replace(/\s*\/\s*$/, '').trim() || '公司未见';
}

export function isJunk(v: string): boolean {
  return !v || /材料未见|材料未标注|材料未公开|未标注/.test(v);
}

export function poolItems(pool?: RadarPool | null): PoolItem[] {
  const items = (pool?.items || []) as PoolItem[];
  return items.filter(it => (it['岗位'] || '').trim() && (it['公司'] || '').trim());
}

/** 从报告 markdown 里去掉所有「表一」段落（避免与机会池面板重复展示）。
 *  容错：支持 `## 表一`、`**表一 · …**`、`表一、` 等写法；到下一个「表X」标题或 --- 结束。
 *  注意：不能用 \b 收尾——中日韩字符不是正则的「单词字符」，`表一\b` 永远匹配不上。 */
export function stripPoolTables(md: string): string {
  if (!md) return md;
  const headRe = /^\s*(?:#{1,4}\s*)?(?:\*\*|__)?\s*表\s*一(?:\s|·|、|:|\||$)/;
  const nextRe = /^\s*(?:#{1,4}\s*)?(?:\*\*|__)?\s*表\s*(?:[二三四五六七八九十]|\d)/;
  const stopRe = /^\s*(?:-{3,}|\*{3,})\s*$/;
  const lines = md.split('\n');
  const out: string[] = [];
  let skipping = false;
  for (const ln of lines) {
    if (!skipping && headRe.test(ln)) { skipping = true; continue; }
    if (skipping && (nextRe.test(ln) || stopRe.test(ln))) skipping = false;
    if (!skipping) out.push(ln);
  }
  return out.join('\n').replace(/\n{3,}/g, '\n\n');
}

export function toCsv(items: PoolItem[]): string {
  if (!items.length) return '';
  const cols = ['级', '岗位', '公司', '地区', '薪资', '福利保障', '经验/学历要求', '发布时间', '来源平台', '链接', '风险标记', 'JD 要点'];
  const esc = (v: string) => `"${(v || '').replace(/"/g, '""')}"`;
  const head = cols.map(esc).join(',');
  const body = items.map(it => cols.map(c => esc(field(it, c) || '')).join(',')).join('\n');
  return `\ufeff${head}\n${body}`;
}
