import { useEffect, useState } from 'react';
import { Clock3, Building2, Search, ShieldCheck, Sparkles, ShieldAlert } from 'lucide-react';
import EnginePicker, { type Engine } from '../components/EnginePicker';
import ResultPanel from '../components/ResultPanel';
import RiskPanel from '../components/RiskPanel';
import SignalsPanel from '../components/SignalsPanel';
import { pickOutput, runWorkflow, type DifyConfig } from '../lib/dify';
import { directBgcheck, directContactMap, type SearchDiagnostics } from '../lib/backend';
import type { Facts } from '../lib/risk';
import type { Signals } from '../lib/signals';
import { useProviders } from '../lib/useProviders';
import { useElapsed } from '../lib/useElapsed';
import { loadLocalDefaults, buildCandidatePrompt } from '../lib/profile';
import { scrollToResult } from '../lib/utils';

const RECENT_KEY = 'jc-bg-recent';
const FACTS_KEY = 'jc-bg-facts';
const MODE_KEY = 'jc-bg-mode';

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (raw) return JSON.parse(raw) as string[];
  } catch { /* ignore */ }
  return [];
}

function loadFacts(): Facts {
  try {
    const raw = localStorage.getItem(FACTS_KEY);
    if (raw) return JSON.parse(raw) as Facts;
  } catch { /* ignore */ }
  return {};
}

interface Props {
  cfg: DifyConfig;
  settingsOpen: boolean;
  openSettings: () => void;
  pushToast: (kind: 'ok' | 'err' | 'info', msg: string) => void;
}

export default function BackgroundView({ cfg, settingsOpen, openSettings, pushToast }: Props) {
  const [company, setCompany] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [result, setResult] = useState('');
  const [recent, setRecent] = useState<string[]>(loadRecent);
  const elapsed = useElapsed(busy);
  const { providers, providerId, select } = useProviders(settingsOpen);
  // V0.3：默认直连模型（独立运行，不再默认依赖 Dify）；如需 Dify 工作流可在页面顶部手动切换
  const [engine, setEngine] = useState<Engine>('direct');
  // 候选人底线画像（local-defaults.json → buildCandidatePrompt），背调按此做雇主风险核查
  const [profile, setProfile] = useState('');
  // 目标企业触点地图（公开渠道联系人与触达路径）
  const [cmBusy, setCmBusy] = useState(false);
  const [cmResult, setCmResult] = useState('');
  const [cmErr, setCmErr] = useState('');
  // 风控升级：体检模式 / 深度风控检索 / 手填工商事实（本地规则层判定）
  const [mode, setMode] = useState<'full' | 'risk'>(() => (localStorage.getItem(MODE_KEY) === 'risk' ? 'risk' : 'full'));
  const [deepRisk, setDeepRisk] = useState(true);
  const [facts, setFacts] = useState<Facts>(loadFacts);
  const [resultTitle, setResultTitle] = useState('背调报告');
  const [resultBadge, setResultBadge] = useState('');
  const [archiveNote, setArchiveNote] = useState('');
  /** 检索诊断（引擎额度/Key/网络问题的真正原因） */
  const [diag, setDiag] = useState<SearchDiagnostics | null>(null);
  const [fixHint, setFixHint] = useState('');
  // 检索材料里的确定性信号（风险关键词 / 利好 / 刷量线索）
  const [signals, setSignals] = useState<Signals | null>(null);
  /** 手工粘贴材料：填了就跳过搜索引擎（搜索额度用尽时的零成本方案） */
  const [manual, setManual] = useState(() => localStorage.getItem('jc-bg-manual') || '');

  useEffect(() => { localStorage.setItem('jc-bg-manual', manual); }, [manual]);

  useEffect(() => {
    loadLocalDefaults().then(d => setProfile(buildCandidatePrompt(d)));
  }, []);

  useEffect(() => {
    localStorage.setItem(MODE_KEY, mode);
  }, [mode]);

  useEffect(() => {
    localStorage.setItem(FACTS_KEY, JSON.stringify(facts));
  }, [facts]);

  useEffect(() => {
    localStorage.setItem('jc-engine-bg', engine);
  }, [engine]);

  useEffect(() => {
    localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
  }, [recent]);

  const run = async (name?: string) => {
    const target = (name ?? company).trim();
    if (!target) {
      pushToast('err', '请先输入公司名称');
      return;
    }
    setBusy(true);
    setErr('');
    setArchiveNote('');
    setDiag(null);
    setFixHint('');
    try {
      if (engine === 'dify') {
        if (!cfg.bgKey) {
          openSettings();
          pushToast('err', '请先填写「公司背调」的 API Key');
          return;
        }
        const r = await runWorkflow(cfg.baseUrl, cfg.bgKey, { company_name: target });
        if (!r.ok) {
          setErr(r.error || '运行失败');
          return;
        }
        setResult(pickOutput(r.outputs, ['report', 'text']));
        setResultTitle('背调报告');
        setResultBadge(target);
        pushToast('ok', '背调报告已生成');
      } else {
        if (!providerId) {
          openSettings();
          pushToast('err', '请先在设置 → 模型直连中添加并选择模型');
          return;
        }
        const r = await directBgcheck(providerId, target, profile, { mode, deepRisk, facts: { ...facts, company_name: target }, manualMaterial: manual.trim() });
        if (!r.ok) {
          setErr(r.error || '运行失败');
          const rr = r as unknown as { diagnostics?: SearchDiagnostics; suggestion?: string };
          if (rr.diagnostics) setDiag(rr.diagnostics);
          if (rr.suggestion) setFixHint(rr.suggestion);
          return;
        }
        setResult(r.content);
        setResultTitle(mode === 'risk' ? '风险体检报告' : '背调报告');
        setResultBadge(mode === 'risk' ? `${target} · 风险体检` : target);
        setSignals((r.signals as Signals | undefined) || null);
        if (r.archive?.ok && r.archive.rel_path) setArchiveNote(`已存档：${r.archive.rel_path}`);
        const s = (r.signals as Signals | undefined)?.summary;
        pushToast('ok', s && s.risk_hits > 0
          ? `${mode === 'risk' ? '风险体检完成' : '背调报告已生成'}：检索材料命中 ${s.risk_hits} 个风险关键词（含一票否决 ${s.risk_veto}）`
          : mode === 'risk' ? '风险体检完成（直连模式）' : '背调报告已生成（直连模式）');
        scrollToResult();
      }
      setRecent(list => [target, ...list.filter(c => c !== target)].slice(0, 6));
    } finally {
      setBusy(false);
    }
  };

  const runContactMap = async () => {
    const target = company.trim();
    if (!target) {
      pushToast('err', '请先输入公司名称');
      return;
    }
    if (engine !== 'direct' || !providerId) {
      openSettings();
      pushToast('err', '触点地图需要直连模型，请先在设置 → 模型直连中添加并选择模型');
      return;
    }
    setCmBusy(true);
    setCmErr('');
    try {
      const r = await directContactMap(providerId, target, profile);
      if (!r.ok) {
        setCmErr(r.error || '生成失败');
        return;
      }
      setCmResult(r.content);
      pushToast('ok', '触点地图已生成（仅公开渠道）');
    } finally {
      setCmBusy(false);
    }
  };

  const phase = mode === 'risk'
    ? (elapsed < 30 ? '风控关键词多路检索（空壳/实缴/失信/欠薪/舆情）…' : elapsed < 70 ? '交叉核对司法与执行记录…' : '撰写风险体检矩阵，即将完成…')
    : elapsed < 40 ? '18 路并行检索工商与舆情信息…' : elapsed < 90 ? '交叉核对风险与监管记录…' : '撰写 16 章节报告，即将完成…';

  return (
    <div className="view">
      <header className="view-head">
        <h2>公司背调</h2>
        <p>VC 尽调 + 风控体检：空壳/套壳、实缴、失信、涉诉、欠薪、舆情、招聘骗局逐项核查，结论可复算、可留档。</p>
      </header>

      <section className="card">
        <EnginePicker
          engine={engine}
          onEngine={setEngine}
          providers={providers}
          providerId={providerId}
          onProvider={select}
          openSettings={openSettings}
          directHint="配置智谱搜索或 Tavily 后可联网检索（设置 → 模型直连）"
        />
        <div className="field">
          <label>公司名称</label>
          <input
            className="input input-lg"
            value={company}
            onChange={e => setCompany(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !busy) run(); }}
            placeholder="例如：河南亿格电器销售有限公司，回车开始背调"
            autoFocus
          />
        </div>
        <details className="manual-box" open={!!manual}>
          <summary>
            手工粘贴材料（搜索额度用尽 / 想用自己搜到的内容时用）
            {manual.trim() && <span className="pill">已填 {manual.length} 字 · 将跳过联网检索</span>}
          </summary>
          <p className="form-hint">
            把从 <b>DeepSeek App / 网页版联网搜索</b>、企查查/天眼查公开页、裁判文书、投诉平台复制的内容粘到这里（每段空一行）。
            填了之后<b>不再调用搜索引擎</b>，但仍会跑：检索材料词库扫描（风险关键词）+ 本地风控规则层 + 18 维度/16 章报告 + 存档。
          </p>
          <textarea
            className="input"
            rows={6}
            value={manual}
            onChange={e => setManual(e.target.value)}
            placeholder={'例如：\n该公司 2024 年因买卖合同纠纷被起诉 3 次，其中 2 次为被告；参保人数 12 人；注册地址为某产业园 3 号楼。\n\n黑猫投诉：提成不发（7 条）、试用期不缴社保（3 条）。'}
          />
          <div className="form-actions">
            <button className="btn btn-ghost btn-sm" onClick={() => setManual('')}>清空粘贴内容</button>
          </div>
        </details>
        <div className="risk-mode-row">
          <label className="check">
            <input type="radio" checked={mode === 'full'} onChange={() => setMode('full')} />
            完整背调（16 章 + 风险矩阵）
          </label>
          <label className="check">
            <input type="radio" checked={mode === 'risk'} onChange={() => setMode('risk')} />
            只做风险体检（更快更省，六节结论）
          </label>
          <label className="check">
            <input type="checkbox" checked={deepRisk} onChange={e => setDeepRisk(e.target.checked)} />
            深度风控检索（+10 路：空壳/换壳/欠薪/税务/破产…）
          </label>
        </div>
        <div className="form-actions">
          <button className="btn btn-primary" onClick={() => run()} disabled={busy || cmBusy}>
            {busy ? <Search size={15} className="spin-once" /> : mode === 'risk' ? <ShieldAlert size={15} /> : <ShieldCheck size={15} />}
            {busy ? `进行中 · 已用 ${elapsed}s` : mode === 'risk' ? '开始风险体检' : '开始背调'}
          </button>
          <button className="btn btn-ghost" onClick={runContactMap} disabled={busy || cmBusy}>
            {cmBusy ? <Sparkles size={15} className="spin-once" /> : <Building2 size={15} />}
            {cmBusy ? '整理中…' : '触点地图（公开渠道）'}
          </button>
          <span className="form-hint">
            {mode === 'risk' ? '12 路风控检索 · 约 1 分钟' : deepRisk ? '18 路搜索（8 基础 + 10 风控）· 约 1–2 分钟' : '8 路搜索 · 约 1 分钟'}
          </span>
        </div>
        {err && (
          <div className="callout callout-err">
            <b>无法完成：</b>{err}
            {fixHint && <div className="form-hint" style={{ marginTop: 6 }}>{fixHint}</div>}
            <div className="form-actions" style={{ marginTop: 8 }}>
              <button className="btn btn-ghost btn-sm" onClick={openSettings}>打开检索设置</button>
            </div>
          </div>
        )}
        {diag?.errors?.length ? (
          <div className="callout callout-warn">
            <b>检索诊断</b>（引擎 {diag.engine}{diag.paths ? ` ｜ ${diag.paths} 路` : ''}{diag.results !== undefined ? ` ｜ 命中 ${diag.results} 条` : ''}）
            {diag.hint && <div style={{ marginTop: 4 }}>{diag.hint}</div>}
            <details style={{ marginTop: 6 }}>
              <summary className="form-hint" style={{ cursor: 'pointer' }}>引擎原始报错</summary>
              <div className="form-hint" style={{ marginTop: 4 }}>{diag.errors.join('；')}</div>
            </details>
          </div>
        ) : null}
        {cmErr && <div className="callout callout-err">{cmErr}</div>}
        {archiveNote && <div className="callout callout-info">📁 {archiveNote}</div>}
      </section>

      <RiskPanel
        company={company.trim()}
        facts={facts}
        onFacts={setFacts}
        onLoadReport={(title, content) => { setResult(content); setResultTitle(title); setResultBadge('存档'); }}
        pushToast={pushToast}
      />

      {recent.length > 0 && (
        <div className="recent">
          <span className="recent-label"><Clock3 size={13} /> 最近背调</span>
          {recent.map(c => (
            <button key={c} className="chip chip-click" onClick={() => !busy && run(c)} disabled={busy}>{c}</button>
          ))}
        </div>
      )}

      {busy && (
        <section className="progress">
          <span>{phase}</span>
          <div className="pbar"><i /></div>
        </section>
      )}

      {!busy && signals && (
        <SignalsPanel signals={signals} title="检索材料信号扫描（风险关键词 / 扩张利好 / 刷量线索）" pushToast={pushToast} />
      )}

      {!busy && result && <ResultPanel title={resultTitle} text={result} badge={resultBadge} />}

      {!busy && !cmBusy && cmResult && (
        <ResultPanel title="目标企业触点地图" text={cmResult} badge="仅公开渠道" />
      )}

      {!busy && !result && !cmResult && (
        <div className="empty">
          <div className="empty-icon"><ShieldCheck size={20} /></div>
          <b>还没有背调报告</b>
          <p>从机会池里挑一家意向公司，输入名称后回车。<br />
            先用「风控体检」手填工商数据（注册资本/实缴/参保人数/被执行/劳动争议）可获得<b>不依赖模型</b>的确定性红旗结论，<br />
            再跑背调让模型补全空壳、换壳、欠薪、舆情、招聘骗局等定性判断；报告与事实会自动存档到 data/intelligence/&lt;公司&gt;/。</p>
        </div>
      )}
    </div>
  );
}
