import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BarChart3, ClipboardCopy, FileText, Gauge, Landmark, Loader2, RefreshCw, Sparkles, Trash2, TrendingUp,
} from 'lucide-react';
import EnginePicker, { type Engine } from '../components/EnginePicker';
import ResultPanel from '../components/ResultPanel';
import MultiSelect from '../components/MultiSelect';
import { INDUSTRY_OPTIONS, REGION_OPTIONS } from '../lib/filterOptions';
import { useProviders } from '../lib/useProviders';
import { useElapsed } from '../lib/useElapsed';
import { loadLocalDefaults, buildCandidatePrompt } from '../lib/profile';
import { scrollToResult } from '../lib/utils';
import { deleteReport, listReports, readReport, type ArchiveItem } from '../lib/risk';
import {
  ARCHIVE_ROOT, directIndustry, evaluateIndustry, fetchIndustryFramework, industryChecklist,
  stageClass,
  type IndustryFacts, type IndustryField, type IndustryFramework, type IndustryResult, type StageScan,
} from '../lib/industry';

const INPUT_KEY = 'jc-industry-inputs';
const FACTS_KEY = 'jc-industry-facts';

interface Props {
  settingsOpen: boolean;
  openSettings: () => void;
  pushToast: (kind: 'ok' | 'err' | 'info', msg: string) => void;
}

interface Inputs {
  industry: string;
  region: string;
}

function loadInputs(): Inputs {
  try {
    const raw = localStorage.getItem(INPUT_KEY);
    if (raw) return { industry: '', region: '河南', ...(JSON.parse(raw) as Partial<Inputs>) };
  } catch { /* ignore */ }
  return { industry: '', region: '河南' };
}

function loadFacts(): IndustryFacts {
  try {
    const raw = localStorage.getItem(FACTS_KEY);
    if (raw) return JSON.parse(raw) as IndustryFacts;
  } catch { /* ignore */ }
  return {};
}

export default function IndustryView({ settingsOpen, openSettings, pushToast }: Props) {
  const [inputs, setInputs] = useState<Inputs>(loadInputs);
  const [facts, setFacts] = useState<IndustryFacts>(loadFacts);
  const [fw, setFw] = useState<IndustryFramework | null>(null);
  const [result, setResult] = useState<IndustryResult | null>(null);
  const [scan, setScan] = useState<StageScan | null>(null);
  const [busy, setBusy] = useState(false);
  const [ruleBusy, setRuleBusy] = useState(false);
  const [report, setReport] = useState('');
  const [err, setErr] = useState('');
  const [ck, setCk] = useState<{ queries: string[]; criteria: Array<{ stage: string; features: string; min: number; verdict: string }> } | null>(null);
  const [archives, setArchives] = useState<ArchiveItem[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [engine, setEngine] = useState<Engine>('direct');
  const [profile, setProfile] = useState('');
  const elapsed = useElapsed(busy);
  const { providers, providerId, select } = useProviders(settingsOpen);

  useEffect(() => {
    fetchIndustryFramework().then(r => { if (r.ok) setFw(r); });
    loadLocalDefaults().then(d => setProfile(buildCandidatePrompt(d)));
  }, []);

  useEffect(() => { localStorage.setItem(INPUT_KEY, JSON.stringify(inputs)); }, [inputs]);
  useEffect(() => { localStorage.setItem(FACTS_KEY, JSON.stringify(facts)); }, [facts]);

  const refreshArchives = useCallback(() => {
    listReports(inputs.industry.trim(), 40, ARCHIVE_ROOT).then(r => { if (r.ok) setArchives(r.items); });
  }, [inputs.industry]);
  useEffect(() => { refreshArchives(); }, [refreshArchives]);

  const setF = (k: string, v: IndustryFacts[string]) => setFacts(f => ({ ...f, [k]: v }));

  const essential = useMemo(() => (fw ? fw.fields.filter(f => f.essential) : []), [fw]);
  const filled = fw ? fw.fields.filter(f => facts[f.key] !== undefined && facts[f.key] !== '').length : 0;

  const cleanFacts = (): IndustryFacts => {
    const out: IndustryFacts = {};
    if (!fw) return out;
    for (const f of fw.fields) {
      const v = facts[f.key];
      if (v === undefined || v === '' || v === null) continue;
      if (f.type === 'number' || f.type === 'int') {
        const n = Number(v);
        if (!Number.isNaN(n)) out[f.key] = f.type === 'int' ? Math.round(n) : n;
      } else if (f.type === 'bool') {
        if (v === true || v === 'true') out[f.key] = true;
        else if (v === false || v === 'false') out[f.key] = false;
      } else out[f.key] = String(v);
    }
    return out;
  };

  const runRule = async () => {
    if (!inputs.industry.trim()) {
      pushToast('err', '请先填写行业名称');
      return;
    }
    setRuleBusy(true);
    try {
      const r = await evaluateIndustry(inputs.industry.trim(), inputs.region.trim(), cleanFacts());
      if (!r.ok) {
        pushToast('err', r.error);
        return;
      }
      setResult(r);
      pushToast('ok', `规则研判：${r.stage.name}（${r.score} 分）`);
    } finally {
      setRuleBusy(false);
    }
  };

  const run = async () => {
    if (!inputs.industry.trim()) {
      pushToast('err', '请先填写行业名称');
      return;
    }
    if (engine !== 'direct' || !providerId) {
      openSettings();
      pushToast('err', '赛道研判需要直连模型，请先在设置 → 模型直连中添加并选择模型');
      return;
    }
    setBusy(true);
    setErr('');
    try {
      const r = await directIndustry(providerId, inputs.industry.trim(), inputs.region.trim(), profile, cleanFacts());
      if (!r.ok) {
        setErr(r.error || '研判失败');
        return;
      }
      setReport(r.content);
      if (r.industry) setResult(r.industry);
      if (r.stage_scan) setScan(r.stage_scan);
      const note = r.archive?.ok && r.archive.rel_path ? `，已存档 ${r.archive.rel_path}` : '';
      pushToast('ok', `赛道研判已生成（${r.paths || 8} 路检索）${note}`);
      refreshArchives();
      scrollToResult();
    } finally {
      setBusy(false);
    }
  };

  const loadChecklist = async () => {
    const r = await industryChecklist(inputs.industry.trim() || '行业', inputs.region.trim());
    if (!r.ok) {
      pushToast('err', r.error);
      return;
    }
    setCk({ queries: r.queries, criteria: r.criteria });
    pushToast('ok', '已生成核查清单（检索关键词 + 五档判据）');
  };

  const copy = async (t: string, msg: string) => {
    try { await navigator.clipboard.writeText(t); pushToast('ok', msg); } catch { pushToast('err', '复制失败'); }
  };

  const openArchive = async (a: ArchiveItem) => {
    const r = await readReport(a.company, a.file, ARCHIVE_ROOT);
    if (!r.ok) { pushToast('err', r.error); return; }
    setReport(r.content);
    pushToast('ok', '已载入存档研判');
  };

  const removeArchive = async (a: ArchiveItem) => {
    const r = await deleteReport(a.company, a.file, ARCHIVE_ROOT);
    if (!r.ok) { pushToast('err', r.error); return; }
    refreshArchives();
  };

  const renderField = (f: IndustryField) => {
    const v = facts[f.key];
    if (f.type === 'bool') {
      return (
        <select className="input" value={v === true ? 'true' : v === false ? 'false' : ''}
          onChange={e => setF(f.key, e.target.value === '' ? undefined : e.target.value === 'true')}>
          <option value="">未填</option><option value="true">是</option><option value="false">否</option>
        </select>
      );
    }
    if (f.type === 'select') {
      return (
        <select className="input" value={v === undefined ? '' : String(v)} onChange={e => setF(f.key, e.target.value || undefined)}>
          <option value="">未填</option>
          {(f.options || []).map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    }
    return (
      <input className="input" type={f.type === 'text' ? 'text' : 'number'} value={v === undefined ? '' : String(v)}
        placeholder={f.help || ''}
        onChange={e => setF(f.key, e.target.value === '' ? undefined : (f.type === 'text' ? e.target.value : Number(e.target.value)))} />
    );
  };

  const stageList = fw?.stages || [];
  const shownFields = fw ? (showAll ? fw.fields : fw.fields) : [];

  return (
    <div className="view">
      <header className="view-head">
        <h2>行业赛道</h2>
        <p>行业生命周期研判：新势力 / 蓝海朝阳 / 平稳存量 / 红海内卷 / 夕阳没落 —— 先按公开事实做确定性判定，再让模型补需求、格局、政策与你的进入时机。</p>
      </header>

      <section className="card">
        <EnginePicker
          engine={engine}
          onEngine={setEngine}
          providers={providers}
          providerId={providerId}
          onProvider={select}
          openSettings={openSettings}
          directHint="未配搜索引擎时只用本地规则层判定（仍然可用）"
        />
        <div className="form-grid">
          <div className="field">
            <label>行业（可多选，取第一个做研判）</label>
            <MultiSelect
              options={INDUSTRY_OPTIONS}
              value={inputs.industry.split(/\s+/).filter(Boolean)}
              onChange={v => setInputs(s => ({ ...s, industry: v.join(' ') }))}
              allowCustom
              placeholder="选择或自定义输入"
            />
          </div>
          <div className="field">
            <label>区域视角</label>
            <MultiSelect
              options={REGION_OPTIONS}
              value={inputs.region.split(/\s+/).filter(Boolean)}
              onChange={v => setInputs(s => ({ ...s, region: v.join(' ') }))}
              allowCustom
              placeholder="如 河南 郑州"
            />
          </div>
        </div>
        <div className="form-actions">
          <button className="btn btn-primary" onClick={run} disabled={busy || ruleBusy}>
            {busy ? <Loader2 size={15} className="spin-once" /> : <Sparkles size={15} />}
            {busy ? `研判中 · 已用 ${elapsed}s` : '生成赛道研判报告'}
          </button>
          <button className="btn btn-ghost" onClick={runRule} disabled={busy || ruleBusy}>
            {ruleBusy ? <Loader2 size={15} className="spin-once" /> : <Gauge size={15} />}
            本地规则判定（秒回，不花钱）
          </button>
          <button className="btn btn-ghost" onClick={loadChecklist} disabled={busy}>
            <ClipboardCopy size={15} /> 核查清单
          </button>
          <span className="form-hint">8 路检索（规模增速/融资/价格战/产能/政策/集中度/招聘/区域产业基础）· 约 1–2 分钟</span>
        </div>
        {err && <div className="callout callout-err">{err}</div>}
      </section>

      <section className="card risk-card">
        <div className="risk-head">
          <div className="risk-head-title">
            <BarChart3 size={15} />
            <b>行业事实（公开数据手填 → 本地规则判定）</b>
            <span className="form-hint">已填 {filled}/{fw?.fields.length || 0} 项；关键 6 项优先，其余可展开</span>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => setShowAll(s => !s)}>
            {showAll ? '只看关键项' : `展开全部 ${fw?.fields.length || 0} 项`}
          </button>
        </div>
        <div className="risk-grid">
          {(showAll ? shownFields : essential).map(f => (
            <div className="field" key={f.key}>
              <label title={f.help || ''}>{f.label}{f.essential && <i className="risk-star">关键</i>}</label>
              {renderField(f)}
            </div>
          ))}
        </div>
      </section>

      {stageList.length > 0 && (
        <section className="card">
          <div className="risk-group-title">五档判据速查（左低右高：分数越高越值得进）</div>
          <div className="stage-row">
            {stageList.map(s => (
              <div className={`stage-card ${stageClass(s.id)} ${result?.stage.id === s.id ? 'active' : ''}`} key={s.id}>
                <div className="stage-badge">{s.badge}</div>
                <b>{s.name}</b>
                <span className="form-hint">≥ {s.min} 分</span>
                <p>{s.features}</p>
                <p className="stage-verdict">{s.entry_verdict}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {result && (
        <section className="card">
          <div className={`risk-result ${stageClass(result.stage.id)}`}>
            <div className="risk-score">
              <div className={`risk-badge ${stageClass(result.stage.id)}`}>{result.stage.badge}</div>
              <div>
                <b>{result.industry} · {result.stage.name}（{result.score}/100）</b>
                <div className="form-hint">
                  置信度 {Math.round(result.confidence * 100)}%
                  {result.missing.length > 0 && ` ｜ 建议补充：${result.missing.join('、')}`}
                  {result.neighbors.length > 0 && ` ｜ 相邻档位：${result.neighbors.map(n => n.name).join(' / ')}`}
                </div>
                <div className="form-hint">进入结论：<b>{result.stage.entry_verdict}</b></div>
              </div>
            </div>

            {[...result.gates, ...result.caps].map(t => (
              <div className="callout callout-info" key={t}>{t}</div>
            ))}

            <div className="risk-findings">
              <div className="risk-finding sev-high">
                <div className="risk-finding-head"><b>机会</b></div>
                <div className="risk-finding-body"><div>{result.stage.opportunity}</div></div>
              </div>
              <div className="risk-finding sev-medium">
                <div className="risk-finding-head"><b>风险</b></div>
                <div className="risk-finding-body"><div>{result.stage.risk}</div></div>
              </div>
              <div className="risk-finding sev-low">
                <div className="risk-finding-head"><b>岗位与谈薪建议</b></div>
                <div className="risk-finding-body"><div>{result.stage.job_advice}</div></div>
              </div>
            </div>

            <div className="risk-ck-item">
              <b>支撑因素</b>
              <div className="risk-ck-q">{result.positive.length ? result.positive.join('　|　') : '（暂无）'}</div>
            </div>
            <div className="risk-ck-item">
              <b>拖累因素</b>
              <div className="risk-ck-q">{result.negative.length ? result.negative.join('　|　') : '（暂无）'}</div>
            </div>
            <div className="risk-ck-item">
              <b>各因子得分</b>
              <div className="risk-ck-q">
                {result.factors.map(f => `${f.label}=${String(f.value)}（${f.points}/1，权重${f.weight}）`).join('　|　')}
              </div>
            </div>

            {scan && scan.dominant && (
              <div className="callout callout-info">
                检索材料词频偏向「{fw?.stages.find(s => s.id === scan.dominant)?.name || scan.dominant}」
                （已剔除检索式回显、按键词数归一）：{scan.hits.slice(0, 8).map(h => `${h.keyword}×${h.count}`).join('、')}
                <br />注意：媒体语言天然偏负面，词频只作交叉参考，<b>档位以规则层判定为准</b>。
              </div>
            )}
          </div>
        </section>
      )}

      {ck && (
        <section className="card">
          <div className="risk-group-title">
            <Landmark size={13} /> 核查清单（复制关键词去官方/券商渠道核对原始数据）
            <button className="btn btn-ghost btn-sm" onClick={() => copy(ck.queries.join('\n'), '已复制检索关键词')}>复制</button>
          </div>
          <div className="sig-chips">{ck.queries.map(q => <span className="sig-tag" key={q}>{q}</span>)}</div>
          <div className="risk-ck-item">
            <b>五档判据</b>
            <div className="risk-ck-q">{ck.criteria.map(c => `${c.stage}（≥${c.min}）：${c.verdict}`).join('　|　')}</div>
          </div>
        </section>
      )}

      {busy && (
        <section className="progress">
          <TrendingUp size={16} className="accent" />
          <span>{elapsed < 30 ? '检索行业规模/融资/价格战/产能/政策…' : elapsed < 70 ? '交叉验证规则层档位与材料特征词…' : '撰写五节研判报告，即将完成…'}</span>
          <div className="pbar"><i /></div>
        </section>
      )}

      {!busy && report && <ResultPanel title="行业赛道研判报告" text={report} badge={inputs.industry.trim()} />}

      <section className="card">
        <div className="risk-group-title">
          <FileText size={13} /> 研判存档
          <span className="form-hint">data/knowledge/_行业/&lt;行业&gt;/ · 可对比不同时间的档位变化</span>
          <button className="btn btn-ghost btn-sm" onClick={refreshArchives}><RefreshCw size={12} /> 刷新</button>
        </div>
        {archives.length === 0 && <div className="form-hint">暂无存档：完成一次赛道研判会自动归档。</div>}
        {archives.map(a => (
          <div className="risk-arc-item" key={`${a.company}/${a.file}`}>
            <button className="link-btn" onClick={() => openArchive(a)}>{a.title}</button>
            <span className="form-hint">{a.file}{a.saved_at ? ` · ${a.saved_at}` : ''}</span>
            <button className="icon-btn" title="删除存档" onClick={() => removeArchive(a)}><Trash2 size={13} /></button>
          </div>
        ))}
      </section>
    </div>
  );
}
