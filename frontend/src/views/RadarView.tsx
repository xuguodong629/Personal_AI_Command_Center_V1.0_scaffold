import { useEffect, useState } from 'react';
import { ArrowRight, ClipboardCheck, ListChecks, Radar as RadarIcon, RefreshCw, Search, Sparkles, Trash2, TrendingUp } from 'lucide-react';
import MultiSelect from '../components/MultiSelect';
import EnginePicker, { type Engine } from '../components/EnginePicker';
import ResultPanel from '../components/ResultPanel';
import SignalsPanel from '../components/SignalsPanel';
import PoolBoard from '../components/PoolBoard';
import { pickOutput, runWorkflow, type DifyConfig } from '../lib/dify';
import { directRadar, directDeep, type RadarPool, type RadarExtras, type SearchDiagnostics } from '../lib/backend';
import type { Signals } from '../lib/signals';
import { useProviders } from '../lib/useProviders';
import { useElapsed } from '../lib/useElapsed';
import { loadLocalDefaults, buildCandidatePrompt } from '../lib/profile';
import { scrollToResult } from '../lib/utils';
import { poolItems, stripPoolTables, type PoolItem } from '../lib/pool';
import {
  JOB_OPTIONS,
  REGION_OPTIONS,
  INDUSTRY_OPTIONS,
  WELFARE_OPTIONS,
  COMPANY_TIER_OPTIONS,
} from '../lib/filterOptions';
import type { ViewId } from '../lib/views';

// 通用默认值。个人简历摘要等敏感信息放在 public/config/local-defaults.json
// （已在 .gitignore 中忽略），页面加载时自动合并，缺失时留空由用户填写。
const DEFAULTS = {
  position_keywords: '区域经理 渠道经理 渠道销售 区域销售 大客户销售',
  regions: '河南 郑州 武汉 西安 上海 深圳 杭州 北京 成都',
  industries: '家电 智能家居 新能源 储能 机器人 工业自动化 智能制造 SaaS 企业服务 消费电子',
  resume_summary: '',
};

const INPUTS_KEY = 'jc-radar-inputs';
const SCAN_KEY = 'jc-radar-scans';
const POOL_KEY = 'jc-radar-pool';

/** 条数设置（用户可选择一次出多少条，以及每路召回多少） */
interface PoolPrefs {
  want: number;
  perQuery: number;
}

function loadPoolPrefs(): PoolPrefs {
  try {
    const raw = localStorage.getItem(POOL_KEY);
    if (raw) return { want: 20, perQuery: 0, ...(JSON.parse(raw) as Partial<PoolPrefs>) };
  } catch { /* ignore */ }
  return { want: 20, perQuery: 0 };
}

const WANT_CHOICES = [10, 20, 30, 50];
const MANUAL_KEY = 'jc-radar-manual';

/** 信号增强开关（默认全开：风险联动 / 扩张利好 / 雇主口碑 / 政策产业） */
interface ScanToggles {
  risk_scan: boolean;
  growth_scan: boolean;
  review_scan: boolean;
  policy_scan: boolean;
}

function loadScans(): ScanToggles {
  try {
    const raw = localStorage.getItem(SCAN_KEY);
    if (raw) return { risk_scan: true, growth_scan: true, review_scan: true, policy_scan: true, ...(JSON.parse(raw) as Partial<ScanToggles>) };
  } catch { /* ignore */ }
  return { risk_scan: true, growth_scan: true, review_scan: true, policy_scan: true };
}

// 薪资档位（对齐智联 / 前程无忧）
const SALARY_PRESETS = [
  { label: '薪资不限', min: 0, max: 0 },
  { label: '3K 以下', min: 0, max: 3000 },
  { label: '3–5K', min: 3000, max: 5000 },
  { label: '5–10K', min: 5000, max: 10000 },
  { label: '10–15K', min: 10000, max: 15000 },
  { label: '15–20K', min: 15000, max: 20000 },
  { label: '20–30K', min: 20000, max: 30000 },
  { label: '30–50K', min: 30000, max: 50000 },
  { label: '50K 以上', min: 50000, max: 0 },
];

function loadInputs(): typeof DEFAULTS {
  try {
    const raw = localStorage.getItem(INPUTS_KEY);
    if (raw) return { ...DEFAULTS, ...(JSON.parse(raw) as Partial<typeof DEFAULTS>) };
  } catch { /* ignore */ }
  return DEFAULTS;
}

interface Props {
  cfg: DifyConfig;
  settingsOpen: boolean;
  radarResult: string;
  setRadarResult: (s: string) => void;
  goTo: (v: ViewId) => void;
  openSettings: () => void;
  pushToast: (kind: 'ok' | 'err' | 'info', msg: string) => void;
}

export default function RadarView({ cfg, settingsOpen, radarResult, setRadarResult, goTo, openSettings, pushToast }: Props) {
  const [inputs, setInputs] = useState(loadInputs);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [investing, setInvesting] = useState(false);
  const [investResult, setInvestResult] = useState('');
  const [investErr, setInvestErr] = useState('');
  const [screening, setScreening] = useState(false);
  const [screenResult, setScreenResult] = useState('');
  const [screenErr, setScreenErr] = useState('');
  const elapsed = useElapsed(busy);
  const { providers, providerId, select } = useProviders(settingsOpen);
  // V0.3：默认直连模型（独立运行，不再默认依赖 Dify）；如需 Dify 工作流可在页面顶部手动切换
  const [engine, setEngine] = useState<Engine>('direct');
  // 候选人画像提示词（local-defaults.json → buildCandidatePrompt），作为后端评分依据
  const [profile, setProfile] = useState('');
  // 本次检索的筛选范围（默认值可用设置页的全局配置覆盖）
  const [scope, setScope] = useState('all');
  const [noOutsourcing, setNoOutsourcing] = useState(false);
  // 定向核查的目标企业（来自 local-defaults.json 的 target_companies）
  const [targetCompanies, setTargetCompanies] = useState('');
  // 招聘网站式精准筛选
  const [tiers, setTiers] = useState<string[]>([]);
  const [salaryMin, setSalaryMin] = useState(0);
  const [salaryMax, setSalaryMax] = useState(0);
  const [expYears, setExpYears] = useState('any');
  const [companySize, setCompanySize] = useState('any');
  const [edu, setEdu] = useState('any');
  const [publishDays, setPublishDays] = useState(0);
  const [jobType, setJobType] = useState('any');
  const [welfareTags, setWelfareTags] = useState('');
  // 信号增强开关 + 最近一次信号扫描结果（确定性词库命中的事实）
  const [scans, setScans] = useState<ScanToggles>(loadScans);
  const [signals, setSignals] = useState<Signals | null>(null);
  // 条数与翻页：一次多出结果，「换一批」增量补充（自动排除已展示条目）
  const [prefs, setPrefs] = useState<PoolPrefs>(loadPoolPrefs);
  const [batch, setBatch] = useState(0);
  const [seenKeys, setSeenKeys] = useState('');
  const [pool, setPool] = useState<RadarPool | null>(null);
  /** 检索诊断（引擎额度/Key/网络问题的真正原因，直接展示在界面上） */
  const [diag, setDiag] = useState<SearchDiagnostics | null>(null);
  const [fixHint, setFixHint] = useState('');
  /** 手工粘贴材料：填了就跳过搜索引擎（搜索额度用尽时的零成本方案） */
  const [manual, setManual] = useState(() => localStorage.getItem(MANUAL_KEY) || '');
  /** 机会池结构化条目（表一的行），跨批次累积，供 PoolBoard 渲染 */
  const [poolItems_, setPoolItems] = useState<PoolItem[]>([]);
  /** 非具体岗位的三类归档（待核实 / 公司监控 / 行业情报）+ 真实性判定统计 */
  const [extras, setExtras] = useState<RadarExtras | null>(null);
  const [pendingItems, setPendingItems] = useState<PoolItem[]>([]);
  const cumulative = seenKeys ? seenKeys.split('；').filter(Boolean).length : 0;

  useEffect(() => { localStorage.setItem(MANUAL_KEY, manual); }, [manual]);

  useEffect(() => {
    localStorage.setItem(SCAN_KEY, JSON.stringify(scans));
  }, [scans]);

  useEffect(() => {
    localStorage.setItem(POOL_KEY, JSON.stringify(prefs));
  }, [prefs]);

  useEffect(() => {
    localStorage.setItem('jc-engine-radar', engine);
  }, [engine]);

  // 输入持久化：切换视图或刷新后不丢
  useEffect(() => {
    localStorage.setItem(INPUTS_KEY, JSON.stringify(inputs));
  }, [inputs]);

  // 加载本地个人默认值（public/config/local-defaults.json，不入库）：填充空字段 + 生成画像提示词
  useEffect(() => {
    loadLocalDefaults().then(d => {
      setProfile(buildCandidatePrompt(d));
      setTargetCompanies((d.target_companies ?? []).join(' '));
      setInputs(prev => ({
        position_keywords: prev.position_keywords || d.position_keywords || '',
        regions: prev.regions || d.regions || '',
        industries: prev.industries || d.industries || '',
        resume_summary: prev.resume_summary || d.resume_summary || '',
      }));
    });
  }, []);

  const set = (patch: Partial<typeof DEFAULTS>) => setInputs(prev => ({ ...prev, ...patch }));

  const run = async (refill = false) => {
    if (!inputs.resume_summary.trim()) {
      pushToast('err', '请先填写简历摘要');
      return;
    }
    setBusy(true);
    setErr('');
    setDiag(null);
    setFixHint('');
    try {
      if (engine === 'dify') {
        if (!cfg.radarKey) {
          openSettings();
          pushToast('err', '请先填写「岗位雷达」的 API Key');
          return;
        }
        const r = await runWorkflow(cfg.baseUrl, cfg.radarKey, inputs);
        if (!r.ok) {
          setErr(r.error || '运行失败');
          return;
        }
        setRadarResult(pickOutput(r.outputs, ['opportunity_pool', 'text']));
        pushToast('ok', '机会池已更新');
      } else {
        if (!providerId) {
          openSettings();
          pushToast('err', '请先在设置 → 模型直连中添加并选择模型');
          return;
        }
        const nextBatch = refill ? batch + 1 : 0;
        const r = await directRadar(providerId, {
          ...inputs,
          profile,
          scope,
          publish_days: publishDays,
          job_type: jobType,
          welfare_tags: welfareTags,
          no_outsourcing: noOutsourcing,
          target_companies: targetCompanies,
          company_tier: tiers.join(','),
          salary_min: salaryMin,
          salary_max: salaryMax,
          exp_years: expYears,
          company_size: companySize,
          edu,
          ...scans,
          want_count: prefs.want,
          per_query: prefs.perQuery,
          batch: nextBatch,
          skip_seen: refill ? seenKeys : '',
          manual_material: manual.trim(),
        });
        if (!r.ok) {
          setErr(r.error || '运行失败');
          const rr = r as unknown as { diagnostics?: SearchDiagnostics; suggestion?: string };
          if (rr.diagnostics) setDiag(rr.diagnostics);
          if (rr.suggestion) setFixHint(rr.suggestion);
          pushToast('err', '检索失败：请看下方诊断（额度/Key/网络）');
          return;
        }
        const p = r.pool;
        if ((r as unknown as { diagnostics?: SearchDiagnostics }).diagnostics) {
          setDiag((r as unknown as { diagnostics?: SearchDiagnostics }).diagnostics || null);
        }
        if (refill && radarResult && p) {
          // 换一批：新批次追加到同一份报告，避免反复检索与来回翻记录
          setRadarResult(`${radarResult}\n\n---\n\n## 第 ${p.batch + 1} 批（新增 ${p.rows} 条）\n\n${r.content}`);
        } else {
          setRadarResult(r.content);
        }
        if (p) {
          setBatch(p.batch);
          setPool(p);
          const newItems = poolItems(p);
          setPoolItems(prev => (refill ? [...prev, ...newItems] : newItems));
          const ex = r as unknown as RadarExtras;
          const newPending = (ex.pending_jobs?.items || []) as PoolItem[];
          setPendingItems(prev => (refill ? [...prev, ...newPending] : newPending));
          setExtras({
            pending_jobs: ex.pending_jobs,
            company_watchlist: ex.company_watchlist,
            industry_intel: ex.industry_intel,
            verification: ex.verification,
          });
          setSeenKeys(prev => {
            const merged = refill ? `${prev}；${p.seen.join('；')}` : p.seen.join('；');
            const items = merged.split('；').filter(Boolean);
            return items.slice(-200).join('；');   // 只留最近 200 条，避免提示词膨胀
          });
        }
        setSignals((r.signals as Signals | undefined) || null);
        const s = (r.signals as Signals | undefined)?.summary;
        pushToast('ok', p
          ? `${refill ? `第 ${p.batch + 1} 批：新增 ${p.rows} 条` : `机会池已生成：${p.rows} 条`}（目标 ${p.want} ｜ ${p.paths} 路 × 每路 ${p.per_query}）`
            + (s ? ` ｜ 风险 ${s.risk_hits} 利好 ${s.growth_hits}` : '')
          : '机会池已生成（直连模式）');
        scrollToResult();
      }
    } finally {
      setBusy(false);
    }
  };

  /** 清空机会池并重置批次（重新开始累计） */
  const resetPool = () => {
    setRadarResult('');
    setBatch(0);
    setSeenKeys('');
    setPool(null);
    setPoolItems([]);
    setPendingItems([]);
    setExtras(null);
    setSignals(null);
    pushToast('info', '已清空机会池，下一批从第 1 批开始');
  };

  const runDeep = async (mode: 'invest' | 'screen') => {
    if (engine !== 'direct' || !providerId) {
      openSettings();
      pushToast('err', '深度分析需要直连模型，请先在设置 → 模型直连中添加并选择模型');
      return;
    }
    if (mode === 'invest') {
      setInvesting(true);
      setInvestErr('');
    } else {
      setScreening(true);
      setScreenErr('');
    }
    try {
      const r = await directDeep(providerId, mode, radarResult, profile);
      if (!r.ok) {
        if (mode === 'invest') setInvestErr(r.error || '分析失败');
        else setScreenErr(r.error || '分析失败');
        return;
      }
      if (mode === 'invest') {
        setInvestResult(r.content);
        pushToast('ok', '潜力企业分析已生成（VC 五步）');
      } else {
        setScreenResult(r.content);
        pushToast('ok', '优秀企业筛选已生成（6 步）');
      }
    } finally {
      if (mode === 'invest') setInvesting(false);
      else setScreening(false);
    }
  };

  const phase = elapsed < 30
    ? '并行检索岗位 + 风险/利好/口碑/政策信号…'
    : elapsed < 70 ? '扫描风险关键词与刷量线索，评估推荐度…' : '汇总机会池，即将完成…';

  /** 把当前目标行业/区域交给「行业赛道」视图（该视图挂载时读取 localStorage） */
  const handoffIndustry = () => {
    const industry = inputs.industries.split(/\s+/).filter(Boolean).slice(0, 3).join(' ');
    const region = inputs.regions.split(/\s+/).filter(Boolean).slice(0, 2).join(' ') || '河南';
    try {
      localStorage.setItem('jc-industry-inputs', JSON.stringify({ industry, region }));
    } catch { /* ignore */ }
    goTo('industry');
  };

  // 多选字段的数组视图（与 inputs 里的空格分隔字符串互转）
  const kwList = inputs.position_keywords.split(/\s+/).filter(Boolean);
  const regionList = inputs.regions.split(/\s+/).filter(Boolean);
  const industryList = inputs.industries.split(/\s+/).filter(Boolean);
  const welfareList = welfareTags.split(/\s+/).filter(Boolean);

  return (
    <div className="view">
      <header className="view-head">
        <h2>岗位雷达</h2>
        <p>并行检索招聘平台 / 领英 / 企业官网机会，优先外企与 500 强；评估五险一金保障，联动公司风险（失信/欠薪/涉诉）、扩张利好（融资/上市/扩产）、雇主口碑与政策产业匹配，并排查疑似刷量岗位。</p>
      </header>

      <section className="card">
        <EnginePicker
          engine={engine}
          onEngine={setEngine}
          providers={providers}
          providerId={providerId}
          onProvider={select}
          openSettings={openSettings}
          directHint="未配搜索引擎时输出方向性建议（含企业质量 / 福利 / 刷量核查维度）"
        />
        <div className="filter-row">
          <span className="filter-title">检索条件</span>
          <label className="filter-item">范围
            <select className="input select-inline" value={scope} onChange={e => setScope(e.target.value)}>
              <option value="all">全部来源</option>
              <option value="job_boards">招聘平台（智联/51job 等）</option>
              <option value="official">企业官网与公告</option>
              <option value="linkedin">领英 LinkedIn</option>
            </select>
          </label>
          <label className="check">
            <input type="checkbox" checked={noOutsourcing} onChange={e => setNoOutsourcing(e.target.checked)} />
            排除外包 / 派遣 / 中介
          </label>
          <span className="form-hint">筛选逻辑对齐智联 / 前程无忧；不满足条件的机会会被降级或排除，并注明原因</span>
        </div>

        <div className="risk-mode-row">
          <span className="filter-title">结果数量</span>
          {WANT_CHOICES.map(n => (
            <label className="check" key={n}>
              <input type="radio" checked={prefs.want === n} onChange={() => setPrefs(p => ({ ...p, want: n }))} />
              {n} 条
            </label>
          ))}
          <label className="filter-item">每路召回
            <select
              className="input select-inline"
              value={prefs.perQuery}
              onChange={e => setPrefs(p => ({ ...p, perQuery: Number(e.target.value) }))}
            >
              <option value={0}>自动</option>
              <option value={5}>5</option>
              <option value={10}>10</option>
              <option value={15}>15</option>
              <option value={20}>20（引擎上限）</option>
            </select>
          </label>
          <span className="form-hint">
            数量越大，路数与每路召回自动上调（10 条≈14 路×5；30 条≈17 路×12；50 条≈20 路×20），耗时与搜索额度同步增加
          </span>
        </div>
        <div className="risk-mode-row">
          <span className="filter-title">信号增强</span>
          <label className="check">
            <input type="checkbox" checked={scans.risk_scan} onChange={e => setScans(s => ({ ...s, risk_scan: e.target.checked }))} />
            ① 公司风险联动（失信/欠薪/被执行/投诉 → 直接标注，禁进高推荐）
          </label>
          <label className="check">
            <input type="checkbox" checked={scans.growth_scan} onChange={e => setScans(s => ({ ...s, growth_scan: e.target.checked }))} />
            ② 扩张利好（融资/上市/扩产/技术突破/中标 → 是否真在扩人）
          </label>
          <label className="check">
            <input type="checkbox" checked={scans.review_scan} onChange={e => setScans(s => ({ ...s, review_scan: e.target.checked }))} />
            ③ 雇主口碑（看准/脉脉/知乎/投诉平台）
          </label>
          <label className="check">
            <input type="checkbox" checked={scans.policy_scan} onChange={e => setScans(s => ({ ...s, policy_scan: e.target.checked }))} />
            ④ 政策与产业（国家/地方规划、扶持目录、产业链上下游）
          </label>
        </div>

        <div className="form-grid filter-panel">
          <div className="field">
            <label>薪资档位</label>
            <select
              className="input"
              value={`${salaryMin}-${salaryMax}`}
              onChange={e => {
                const [lo, hi] = e.target.value.split('-').map(Number);
                setSalaryMin(lo || 0);
                setSalaryMax(hi || 0);
              }}
            >
              {SALARY_PRESETS.map(p => (
                <option key={p.label} value={`${p.min}-${p.max}`}>{p.label}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>薪资自定义（元，可空）</label>
            <div className="inline-2">
              <input className="input num-input" type="number" placeholder="下限" value={salaryMin || ''} onChange={e => setSalaryMin(Number(e.target.value) || 0)} />
              <span className="form-hint">—</span>
              <input className="input num-input" type="number" placeholder="上限" value={salaryMax || ''} onChange={e => setSalaryMax(Number(e.target.value) || 0)} />
            </div>
          </div>
          <div className="field">
            <label>工作经验</label>
            <select className="input" value={expYears} onChange={e => setExpYears(e.target.value)}>
              <option value="any">不限</option>
              <option value="1-3">1–3 年</option>
              <option value="3-5">3–5 年</option>
              <option value="5-10">5–10 年</option>
              <option value="10+">10 年以上</option>
            </select>
          </div>
          <div className="field">
            <label>学历要求</label>
            <select className="input" value={edu} onChange={e => setEdu(e.target.value)}>
              <option value="any">不限</option>
              <option value="中专">中专及以上</option>
              <option value="高中">高中及以上</option>
              <option value="大专">大专及以上</option>
              <option value="本科">本科及以上</option>
              <option value="硕士">硕士及以上</option>
              <option value="博士">博士</option>
            </select>
          </div>
          <div className="field">
            <label>公司性质（多选）</label>
            <MultiSelect
              options={COMPANY_TIER_OPTIONS}
              value={tiers}
              onChange={setTiers}
              placeholder="不限（可多选）"
            />
          </div>
          <div className="field">
            <label>公司规模</label>
            <select className="input" value={companySize} onChange={e => setCompanySize(e.target.value)}>
              <option value="any">不限</option>
              <option value="0-19">20 人以下</option>
              <option value="20-99">20–99 人</option>
              <option value="100-499">100–499 人</option>
              <option value="500-999">500–999 人</option>
              <option value="1000-9999">1000–9999 人</option>
              <option value="10000+">10000 人以上</option>
            </select>
          </div>
          <div className="field">
            <label>发布时间</label>
            <select className="input" value={publishDays} onChange={e => setPublishDays(Number(e.target.value))}>
              <option value={0}>不限</option>
              <option value={1}>24 小时内</option>
              <option value={3}>近 3 天</option>
              <option value={7}>近 7 天</option>
              <option value={30}>近 30 天</option>
            </select>
          </div>
          <div className="field">
            <label>职位类型</label>
            <select className="input" value={jobType} onChange={e => setJobType(e.target.value)}>
              <option value="any">不限</option>
              <option value="全职">全职</option>
              <option value="兼职">兼职</option>
              <option value="实习">实习</option>
            </select>
          </div>
          <div className="field">
            <label>福利标签（多选）</label>
            <MultiSelect
              options={WELFARE_OPTIONS}
              value={welfareList}
              onChange={v => setWelfareTags(v.join(' '))}
              allowCustom
              placeholder="五险一金 / 双休 …"
            />
          </div>
        </div>
        <div className="form-grid filter-panel">
          <div className="field">
            <label>岗位关键词（多选）</label>
            <MultiSelect
              options={JOB_OPTIONS}
              value={kwList}
              onChange={v => set({ position_keywords: v.join(' ') })}
              allowCustom
              placeholder="选择或自定义输入"
            />
          </div>
          <div className="field">
            <label>目标区域（多选）</label>
            <MultiSelect
              options={REGION_OPTIONS}
              value={regionList}
              onChange={v => set({ regions: v.join(' ') })}
              allowCustom
              placeholder="选择或自定义输入"
            />
          </div>
          <div className="field">
            <label>目标行业（多选）</label>
            <MultiSelect
              options={INDUSTRY_OPTIONS}
              value={industryList}
              onChange={v => set({ industries: v.join(' ') })}
              allowCustom
              placeholder="选择或自定义输入"
            />
          </div>
        </div>
        <div className="field">
          <label>简历摘要</label>
          <textarea
            className="input"
            rows={3}
            value={inputs.resume_summary}
            onChange={e => set({ resume_summary: e.target.value })}
            placeholder="填写你的简历摘要（可放入 public/config/local-defaults.json 自动加载）"
          />
        </div>
        <details className="manual-box" open={!!manual}>
          <summary>
            手工粘贴材料（搜索额度用尽 / 想用自己搜到的内容时用）
            {manual.trim() && <span className="pill">已填 {manual.length} 字 · 将跳过联网检索</span>}
          </summary>
          <p className="form-hint">
            把你在 <b>DeepSeek App / 网页版联网搜索</b>、招聘 App、企业官网等处搜到的 JD、薪资、公司动态粘到这里（每段之间空一行更好）。
            填了之后<b>不再调用任何搜索引擎</b>，但照样走：词库风险扫描 → 画像加权评分 → 六张表输出。
          </p>
          <textarea
            className="input"
            rows={6}
            value={manual}
            onChange={e => setManual(e.target.value)}
            placeholder={'例如：\n美的集团 河南 区域经理（郑州）｜BOSS直聘｜10-15K·13薪｜五险一金｜3-5年｜职责：…\n\n海尔智家 渠道经理｜智联｜12-18K｜要求：…'}
          />
          <div className="form-actions">
            <button className="btn btn-ghost btn-sm" onClick={() => setManual('')}>清空粘贴内容</button>
            <span className="form-hint">材料里的「失信/欠薪/投诉/长期招聘」等词仍会被确定性词库扫出来并标注</span>
          </div>
        </details>
        <div className="form-actions">
          <button className="btn btn-primary" onClick={() => run(false)} disabled={busy}>
            {busy ? <Search size={15} className="spin-once" /> : <RadarIcon size={15} />}
            {busy ? `搜索中 · 已用 ${elapsed}s` : manual.trim() ? `开始分析（粘贴材料 · 目标 ${prefs.want} 条）` : `开始搜索（目标 ${prefs.want} 条）`}
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => run(true)}
            disabled={busy || !radarResult || engine !== 'direct' || !!manual.trim()}
            title={manual.trim() ? '粘贴材料模式下不能"换一批"（换一批依赖搜索引擎轮换新的检索组合）' : '继续检索并自动排除已展示过的公司与岗位，结果追加到同一份报告'}
          >
            {busy ? <RefreshCw size={15} className="spin-once" /> : <RefreshCw size={15} />}
            换一批（排除已展示）
          </button>
          <button className="btn btn-ghost" onClick={resetPool} disabled={busy || !radarResult}>
            <Trash2 size={15} /> 清空重来
          </button>
          <span className="form-hint">
            {pool
              ? `本批 ${pool.rows}/${pool.want} 条 · 第 ${pool.batch + 1} 批 · ${pool.paths} 路 × 每路 ${pool.per_query} · 累计已获取 ${cumulative} 条`
              : `${8 + (scans.risk_scan ? 1 : 0) + (scans.growth_scan ? 2 : 0) + (scans.review_scan ? 2 : 0) + (scans.policy_scan ? 3 : 0)} 路起 · 约 1–3 分钟`}
          </span>
        </div>
        {err && (
          <div className="callout callout-err">
            <b>检索失败：</b>{err}
            {fixHint && <div className="form-hint" style={{ marginTop: 6 }}>{fixHint}</div>}
            <div className="form-actions" style={{ marginTop: 8 }}>
              <button className="btn btn-ghost btn-sm" onClick={openSettings}>打开检索设置</button>
            </div>
          </div>
        )}
        {diag && (diag.errors?.length || diag.empty_paths) ? (
          <div className="callout callout-warn">
            <b>检索诊断</b>（引擎 {diag.engine}
            {diag.paths ? ` ｜ ${diag.paths} 路 × 每路 ${diag.per_query}` : ''}
            {diag.results !== undefined ? ` ｜ 命中 ${diag.results} 条` : ''}
            {diag.empty_paths ? ` ｜ 空结果 ${diag.empty_paths} 路` : ''}
            {diag.cache_hits ? ` ｜ 缓存命中 ${diag.cache_hits} 次` : ''}）
            {diag.hint && <div style={{ marginTop: 4 }}>{diag.hint}</div>}
            {diag.errors?.length ? (
              <details style={{ marginTop: 6 }}>
                <summary className="form-hint" style={{ cursor: 'pointer' }}>引擎原始报错（{diag.errors.length} 条）</summary>
                <div className="form-hint" style={{ marginTop: 4 }}>{diag.errors.join('；')}</div>
              </details>
            ) : null}
            {diag.relaxed_used?.length ? (
              <div className="form-hint" style={{ marginTop: 4 }}>
                已用放宽查询补检索：{diag.relaxed_used.join('；')}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      {pool && !busy && (
        <div className="recent">
          <span className="recent-label">
            <ListChecks size={13} /> 本批 {pool.rows} 条 / 目标 {pool.want} 条
          </span>
          <span className="form-hint">
            已检索 {pool.paths} 路 × 每路 {pool.per_query} 条；累计去重条目 {cumulative} 条 · 结果不足时可点「换一批」继续（自动排除已展示项）
          </span>
        </div>
      )}

      {busy && (
        <section className="progress">
          <Sparkles size={16} className="accent" />
          <span>{phase}</span>
          <div className="pbar"><i /></div>
        </section>
      )}

      {!busy && signals && <SignalsPanel signals={signals} pushToast={pushToast} />}

      {!busy && poolItems_.length > 0 && (
        <PoolBoard items={poolItems_} title="今日具体岗位（通过真实性校验）" pushToast={pushToast} />
      )}

      {!busy && poolItems_.length === 0 && extras?.verification && (
        <section className="card">
          <div className="callout callout-warn">
            <b>本次没有「通过真实性校验」的具体岗位</b>
            （候选 {extras.verification.candidates} 条 → 通过 {extras.verification.verified} ｜ 待核实 {extras.verification.pending} ｜ 排除 {extras.verification.invalid}）
            <div className="form-hint" style={{ marginTop: 6 }}>
              规则：{extras.verification.rule}
            </div>
            {extras.verification.invalid_samples?.length ? (
              <div className="form-hint" style={{ marginTop: 4 }}>
                被排除的示例：{extras.verification.invalid_samples.join(' ｜ ')}
              </div>
            ) : null}
            <div className="form-hint" style={{ marginTop: 4 }}>
              这不是检索失败：宁可 0 条，也不用公司情报凑岗位。可在下方「待核实岗位」里找线索。
            </div>
          </div>
        </section>
      )}

      {!busy && pendingItems.length > 0 && (
        <PoolBoard items={pendingItems} title="待核实岗位（有招聘迹象，缺关键字段）" variant="pending" pushToast={pushToast} />
      )}

      {!busy && (extras?.company_watchlist?.rows || extras?.industry_intel?.rows) ? (
        <section className="card">
          {extras?.company_watchlist?.rows ? (
            <>
              <div className="risk-group-title">目标公司监控（公司值得盯，但没有具体岗位证据）</div>
              <div className="pool-table-wrap">
                <table className="pool-table">
                  <tbody>
                    {(extras.company_watchlist.items || []).map((w, i) => (
                      <tr key={`w-${i}`}>
                        <td className="nowrap-cell">{w['公司'] || '—'}</td>
                        <td>{w['为什么值得监控'] || w['理由'] || '—'}</td>
                        <td className="form-hint">{w['依据'] || ''}</td>
                        <td className="form-hint">{w['监控动作'] || w['建议'] || ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
          {extras?.industry_intel?.rows ? (
            <>
              <div className="risk-group-title" style={{ marginTop: 12 }}>行业情报（政策 / 新闻 / 扩产 / 融资）</div>
              <div className="pool-table-wrap">
                <table className="pool-table">
                  <tbody>
                    {(extras.industry_intel.items || []).map((w, i) => (
                      <tr key={`i-${i}`}>
                        <td className="nowrap-cell">{w['主题'] || '—'}</td>
                        <td>{w['内容'] || '—'}</td>
                        <td className="form-hint">{w['依据'] || ''}</td>
                        <td className="form-hint">{w['对我们的意义'] || w['意义'] || ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </section>
      ) : null}

      {!busy && radarResult && (
        <ResultPanel
          title={poolItems_.length > 0 ? '完整报告（评分 / 解析 / 风险 / 利好 / 来源）' : '今日机会池'}
          text={poolItems_.length > 0 ? stripPoolTables(radarResult) : radarResult}
          badge="岗位雷达"
          footer={
            <div className="next-steps">
              <button className="btn btn-ghost btn-sm" onClick={handoffIndustry}>
                下一步：行业赛道研判 <ArrowRight size={13} />
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => goTo('bg')}>
                下一步：公司背调 <ArrowRight size={13} />
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => goTo('resume')}>
                下一步：定制简历 <ArrowRight size={13} />
              </button>
            </div>
          }
        />
      )}

      {!busy && radarResult && engine === 'direct' && providerId && (
        <section className="card">
          <div className="form-actions">
            <button className="btn btn-primary" onClick={() => runDeep('invest')} disabled={investing || screening}>
              {investing ? <Sparkles size={15} className="spin-once" /> : <TrendingUp size={15} />}
              {investing ? '投资视角分析中…' : '投资视角 · 潜力企业深挖'}
            </button>
            <button className="btn btn-primary" onClick={() => runDeep('screen')} disabled={investing || screening}>
              {screening ? <Sparkles size={15} className="spin-once" /> : <ClipboardCheck size={15} />}
              {screening ? '筛选分析中…' : '优秀企业筛选（6 步）'}
            </button>
            <span className="form-hint">按画像执行深度分析：投资逻辑选潜力股 / 6 步评估筛好企业</span>
          </div>
        </section>
      )}
      {investErr && <div className="callout callout-err">{investErr}</div>}
      {screenErr && <div className="callout callout-err">{screenErr}</div>}
      {!busy && !investing && investResult && (
        <ResultPanel title="投资视角 · 潜力企业深挖" text={investResult} badge="VC 投委会" />
      )}
      {!busy && !screening && screenResult && (
        <ResultPanel title="优秀企业筛选 · 6 步评估" text={screenResult} badge="筛选评估" />
      )}

      {!busy && !radarResult && (
        <div className="empty">
          <div className="empty-icon"><RadarIcon size={20} /></div>
          <b>还没有机会池</b>
          <p>确认上方三组关键词与简历摘要后，点击「开始搜索」。<br />机会池生成后，可直接把意向岗位的 JD 送往下两步继续分析。</p>
        </div>
      )}
    </div>
  );
}
