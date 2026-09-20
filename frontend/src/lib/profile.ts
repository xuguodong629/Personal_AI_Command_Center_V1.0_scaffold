// 本地个人默认值与候选人画像（frontend/public/config/local-defaults.json，不入 git）
// 用途：岗位雷达 / 公司背调 / 定制简历 共用一份「候选人画像 + 优先级 + 底线 + 评分权重」，
// 页面加载时拉取，拼成一段自包含的提示词文本传给后端，让 AI 按画像评估。

export interface CandidateProfile {
  name?: string;
  age?: number;
  years?: number;
  base?: string;
  target_roles?: string;
  target_regions?: string;
  salary_expect?: string;
  positioning?: string;
  core_strengths?: string[];
  background?: string;
  education?: string;
}

export interface LocalDefaults {
  position_keywords?: string;
  regions?: string;
  industries?: string;
  resume_summary?: string;
  /** 定向核查的目标企业（雷达会为它们生成专门查询） */
  target_companies?: string[];
  candidate?: CandidateProfile;
  match_prefs?: string[];
  hard_rules?: string[];
  scoring?: {
    weights?: Record<string, number>;
    tiers?: { priority?: number; caution?: number };
  };
}

let cache: LocalDefaults | null = null;

/** 拉取本地默认配置（只拉一次，失败返回空对象） */
export async function loadLocalDefaults(): Promise<LocalDefaults> {
  if (cache) return cache;
  try {
    const res = await fetch('/config/local-defaults.json');
    if (res.ok) cache = (await res.json()) as LocalDefaults;
  } catch { /* ignore */ }
  return cache ?? {};
}

/** 把候选人配置拼成一段自包含的中文提示词段落（后端评分依据） */
export function buildCandidatePrompt(d: LocalDefaults): string {
  const c = d.candidate ?? {};
  const lines: string[] = [];

  lines.push('【候选人画像（真实信息，勿改动）】');
  const head: string[] = [];
  if (c.name) head.push(`姓名：${c.name}`);
  if (c.age) head.push(`${c.age} 岁`);
  if (c.years) head.push(`${c.years} 年工作经验`);
  if (c.base) head.push(`base ${c.base}`);
  if (head.length) lines.push(`- ${head.join('，')}`);
  if (c.target_roles) lines.push(`- 目标岗位：${c.target_roles}`);
  if (c.target_regions) lines.push(`- 目标地区：${c.target_regions}`);
  if (c.salary_expect) lines.push(`- 期望薪资：${c.salary_expect}`);
  if (c.positioning) lines.push(`- 定位：${c.positioning}`);
  if (c.background) lines.push(`- 行业背景：${c.background}`);
  if (c.education) lines.push(`- 学历：${c.education}`);
  if (c.core_strengths?.length) {
    lines.push('- 核心能力：');
    c.core_strengths.forEach((s, i) => lines.push(`  ${i + 1}. ${s}`));
  }

  if (d.match_prefs?.length) {
    lines.push('');
    lines.push(`【求职优先级】${d.match_prefs.join(' > ')}`);
  }

  if (d.hard_rules?.length) {
    lines.push('');
    lines.push('【底线（硬伤，命中任一条即直接排除）】');
    d.hard_rules.forEach((r, i) => lines.push(`${i + 1}. ${r}`));
  }

  const w = d.scoring?.weights;
  if (w) {
    lines.push('');
    lines.push('【评分权重表】');
    lines.push('| 维度 | 权重 |');
    lines.push('|---|---|');
    Object.entries(w).forEach(([k, v]) => lines.push(`| ${k} | ${v}% |`));
    const t = d.scoring?.tiers ?? {};
    lines.push(
      `总分 ≥${t.priority ?? 80} 优先投递；${t.caution ?? 60}–${(t.priority ?? 80) - 1} 谨慎；<${t.caution ?? 60} 排除（命中底线直接排除）。`,
    );
  }

  return lines.join('\n');
}
