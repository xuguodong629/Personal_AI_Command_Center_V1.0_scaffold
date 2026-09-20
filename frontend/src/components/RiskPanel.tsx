import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, ClipboardList, ExternalLink, FileText, Gauge,
  Loader2, RefreshCw, ShieldAlert, Trash2, Wand2,
} from 'lucide-react';
import { openExternal } from '../lib/backend';
import {
  cleanFacts, deleteReport, evaluateRisk, fetchChecklist, fetchRiskMeta, levelClass,
  listReports, readReport, SEVERITY_ORDER,
  type ArchiveItem, type ChecklistItem, type Facts, type FactsField, type Portal,
  type RiskMeta, type RiskResult,
} from '../lib/risk';

interface Props {
  company: string;
  facts: Facts;
  onFacts: (f: Facts) => void;
  /** 读存档后回填到报告区 */
  onLoadReport: (title: string, content: string) => void;
  pushToast: (kind: 'ok' | 'err' | 'info', msg: string) => void;
}

export default function RiskPanel({ company, facts, onFacts, onLoadReport, pushToast }: Props) {
  const [meta, setMeta] = useState<RiskMeta | null>(null);
  const [result, setResult] = useState<RiskResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [checklist, setChecklist] = useState<ChecklistItem[] | null>(null);
  const [portals, setPortals] = useState<Portal[]>([]);
  const [ckBusy, setCkBusy] = useState(false);
  const [archives, setArchives] = useState<ArchiveItem[]>([]);
  const [arcDir, setArcDir] = useState('');
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    fetchRiskMeta().then(r => { if (r.ok) setMeta(r); });
  }, []);

  const refreshArchives = useCallback(() => {
    listReports(company).then(r => {
      if (r.ok) {
        setArchives(r.items);
        setArcDir(r.dir);
      }
    });
  }, [company]);

  useEffect(() => { refreshArchives(); }, [refreshArchives]);

  const set = (key: string, v: Facts[string]) => onFacts({ ...facts, [key]: v });

  const essentialCount = useMemo(() => (meta ? meta.fields.filter(f => f.essential).length : 0), [meta]);
  const filledCount = meta ? meta.fields.filter(f => facts[f.key] !== undefined && facts[f.key] !== '').length : 0;

  const runCheck = async () => {
    if (!meta) return;
    setBusy(true);
    try {
      const r = await evaluateRisk(cleanFacts(meta.fields, facts, company));
      if (!r.ok) {
        pushToast('err', r.error);
        return;
      }
      setResult(r);
      pushToast(r.veto ? 'err' : 'ok', r.veto ? `命中一票否决风险（${r.level}）` : `体检完成：${r.level}（${r.score} 分）`);
    } finally {
      setBusy(false);
    }
  };

  const loadChecklist = async () => {
    setCkBusy(true);
    try {
      const r = await fetchChecklist(company || '公司名称');
      if (!r.ok) {
        pushToast('err', r.error);
        return;
      }
      setChecklist(r.items);
      setPortals(r.portals);
      pushToast('ok', `已生成 ${r.items.length} 项核查清单（含检索关键词与官方入口）`);
    } finally {
      setCkBusy(false);
    }
  };

  const copy = async (text: string, label = '已复制') => {
    try {
      await navigator.clipboard.writeText(text);
      pushToast('ok', label);
    } catch {
      pushToast('err', '复制失败，请手动选择文本');
    }
  };

  const openUrl = async (url: string) => {
    const r = await openExternal(url);
    if (!r.ok) pushToast('err', r.error);
  };

  const openArchive = async (item: ArchiveItem) => {
    const r = await readReport(item.company, item.file);
    if (!r.ok) {
      pushToast('err', r.error);
      return;
    }
    onLoadReport(`${item.company} · ${item.kind}（${item.file}）`, r.content);
    pushToast('ok', '已载入存档报告');
  };

  const removeArchive = async (item: ArchiveItem) => {
    const r = await deleteReport(item.company, item.file);
    if (!r.ok) {
      pushToast('err', r.error);
      return;
    }
    pushToast('info', '已删除存档');
    refreshArchives();
  };

  const renderField = (f: FactsField) => {
    const v = facts[f.key];
    if (f.type === 'bool') {
      return (
        <select className="input" value={v === true ? 'true' : v === false ? 'false' : ''}
          onChange={e => set(f.key, e.target.value === '' ? undefined : e.target.value === 'true')}>
          <option value="">未填</option>
          <option value="true">是</option>
          <option value="false">否</option>
        </select>
      );
    }
    if (f.type === 'select') {
      return (
        <select className="input" value={v === undefined ? '' : String(v)} onChange={e => set(f.key, e.target.value || undefined)}>
          <option value="">未填</option>
          {(f.options || []).map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    }
    return (
      <input
        className="input"
        type={f.type === 'text' ? 'text' : 'number'}
        value={v === undefined ? '' : String(v)}
        placeholder={f.help || ''}
        onChange={e => set(f.key, e.target.value === '' ? undefined : (f.type === 'text' ? e.target.value : Number(e.target.value)))}
      />
    );
  };

  const groups = meta?.groups || [];
  const findingsBy = (sev: string) => (result?.findings || []).filter(f => f.severity === sev);

  return (
    <section className="card risk-card">
      <div className="risk-head">
        <div className="risk-head-title">
          <ShieldAlert size={15} />
          <b>风控体检</b>
          <span className="form-hint">
            公开工商／司法／舆情事实手填 → 本地规则层判定（不依赖模型、可复算）
          </span>
        </div>
        <div className="risk-head-actions">
          {meta && <span className="form-hint">已填 {filledCount}/{meta.fields.length} 项（关键 {essentialCount} 项）</span>}
          <button className="btn btn-ghost btn-sm" onClick={() => setExpanded(e => !e)}>
            {expanded ? '收起' : '展开'}
          </button>
        </div>
      </div>

      {expanded && (
        <>
          <div className="callout callout-info risk-tip">
            先花 3 分钟在<a className="link-btn" onClick={() => openUrl('https://www.gsxt.gov.cn/')}>国家企业信用信息公示系统</a>
            、<a className="link-btn" onClick={() => openUrl('http://zxgk.court.gov.cn/')}>执行信息公开网</a>
            、<a className="link-btn" onClick={() => openUrl('https://wenshu.court.gov.cn/')}>裁判文书网</a>
            抄下数据（尤其<b>注册资本 / 实缴 / 参保人数 / 被执行 / 劳动争议</b>），命中一票否决项会直接给出结论。
          </div>

          {!meta && <div className="form-hint">正在读取风控字段…</div>}

          {meta && (
            <>
              <div className="risk-groups">
                {groups.map(g => {
                  const fields = meta.fields.filter(f => f.group === g && (showAll || f.essential));
                  if (!fields.length) return null;
                  return (
                    <div className="risk-group" key={g}>
                      <div className="risk-group-title">{g}</div>
                      <div className="risk-grid">
                        {fields.map(f => (
                          <div className="field" key={f.key}>
                            <label title={f.help || ''}>
                              {f.label}
                              {f.essential && <i className="risk-star">关键</i>}
                            </label>
                            {renderField(f)}
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="form-actions">
                <button className="btn btn-primary btn-sm" onClick={runCheck} disabled={busy}>
                  {busy ? <Loader2 size={14} className="spin-once" /> : <Gauge size={14} />}
                  {busy ? '体检中…' : '开始体检（本地规则）'}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => setShowAll(s => !s)}>
                  {showAll ? '只看关键字段' : `展开全部 ${meta.fields.length} 项`}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={loadChecklist} disabled={ckBusy}>
                  {ckBusy ? <Loader2 size={14} className="spin-once" /> : <ClipboardList size={14} />}
                  核查清单（关键词+官方入口）
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => { onFacts({}); setResult(null); pushToast('info', '已清空手填事实'); }}>
                  <Trash2 size={14} /> 清空事实
                </button>
              </div>
            </>
          )}

          {result && (
            <div className={`risk-result ${levelClass(result.level)}`}>
              <div className="risk-score">
                <div className={`risk-badge ${levelClass(result.level)}`}>{result.level}</div>
                <div>
                  <b>风险分 {result.score}/100</b>
                  <div className="form-hint">{result.level_hint}</div>
                  <div className="form-hint">
                    事实完整度 {Math.round(result.confidence * 100)}%
                    {result.missing.length > 0 && ` ｜ 建议补充：${result.missing.slice(0, 5).join('、')}${result.missing.length > 5 ? ' 等' : ''}`}
                  </div>
                </div>
              </div>

              {result.veto && (
                <div className="callout callout-err risk-veto">
                  <AlertTriangle size={14} /> 命中 <b>一票否决</b>：
                  {result.findings.filter(f => f.severity === 'veto').map(f => f.title).join('；')}
                </div>
              )}

              <div className="risk-counts">
                {SEVERITY_ORDER.map(s => (
                  result.counts[s] > 0 && (
                    <span key={s} className={`risk-chip sev-${s}`}>
                      {meta?.severity_label[s] || s} {result.counts[s]}
                    </span>
                  )
                ))}
                {result.findings.length === 0 && <span className="risk-chip sev-ok"><CheckCircle2 size={12} /> 已填范围内未命中红旗</span>}
              </div>

              {SEVERITY_ORDER.map(sev => {
                const list = findingsBy(sev);
                if (!list.length) return null;
                return (
                  <div className="risk-findings" key={sev}>
                    {list.map(f => (
                      <div className={`risk-finding sev-${f.severity}`} key={f.id}>
                        <div className="risk-finding-head">
                          <span className={`risk-chip sev-${f.severity}`}>{f.severity_label}</span>
                          <b>{f.title}</b>
                          <span className="risk-dim">{f.dimension}</span>
                        </div>
                        <div className="risk-finding-body">
                          <div><i>依据</i>{f.detail}</div>
                          <div><i>核实</i>{f.verify}</div>
                          {f.advice && <div><i>处理</i>{f.advice}</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          )}

          {checklist && (
            <div className="risk-checklist">
              <div className="risk-group-title">
                <Wand2 size={13} /> 核查清单（复制关键词到搜索引擎／官方平台逐项自查）
              </div>
              <div className="risk-portals">
                {portals.map(p => (
                  <button key={p.url} className="chip chip-click" onClick={() => open(p.url)} title={p.use}>
                    {p.name} <ExternalLink size={11} />
                  </button>
                ))}
              </div>
              {checklist.map(item => (
                <div className="risk-ck-item" key={item.id}>
                  <b>{item.name}</b>
                  <span className="risk-chip">{item.weight}</span>
                  <button className="btn btn-ghost btn-sm" onClick={() => copy(item.queries.join('\n'), '已复制该维度检索关键词')}>复制关键词</button>
                  <div className="risk-ck-q">{item.queries.join('　|　')}</div>
                  <div className="form-hint">核实：{item.verify}</div>
                </div>
              ))}
            </div>
          )}

          <div className="risk-archive">
            <div className="risk-group-title">
              <FileText size={13} /> 报告存档
              <span className="form-hint">{arcDir ? `${arcDir}/` : 'data/intelligence/'}</span>
              <button className="btn btn-ghost btn-sm" onClick={refreshArchives}><RefreshCw size={12} /> 刷新</button>
            </div>
            {archives.length === 0 && <div className="form-hint">暂无存档：完成一次背调或风险体检会自动归档到公司目录。</div>}
            {archives.map(a => (
              <div className="risk-arc-item" key={`${a.company}/${a.file}`}>
                <button className="link-btn" onClick={() => openArchive(a)}>
                  {a.company} · {a.kind}{a.risk ? ` · 风险${a.risk}` : ''}
                </button>
                <span className="form-hint">{a.file}{a.saved_at ? ` · ${a.saved_at}` : ''}</span>
                <button className="icon-btn" title="删除存档" onClick={() => removeArchive(a)}><Trash2 size={13} /></button>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
