import { useState } from 'react';
import {
  AlertTriangle, ClipboardCopy, Landmark, Minus, ShieldAlert, TrendingUp,
} from 'lucide-react';
import { SEVERITY_LABEL, SEVERITY_ORDER, type Signals } from '../lib/signals';

interface Props {
  signals?: Signals | null;
  title?: string;
  /** 折叠初始状态 */
  defaultOpen?: boolean;
  pushToast?: (kind: 'ok' | 'err' | 'info', msg: string) => void;
}

/** 确定性信号面板：风险关键词 / 扩张利好 / 刷量线索 / 政策产业检索路。
 *  这些是词库命中的事实，即使模型漏读也能在这里看见。 */
export default function SignalsPanel({ signals, title = '信号扫描（确定性词库）', defaultOpen = true, pushToast }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const [showAll, setShowAll] = useState(false);

  if (!signals) return null;
  const risk = signals.risk || [];
  const growth = signals.growth || [];
  const volume = signals.volume || [];
  const rules = signals.volume_rules || [];
  const policies = signals.policy_queries || [];
  const sum = signals.summary;
  const total = risk.length + growth.length + volume.length + rules.length;

  const copy = async (text: string, msg: string) => {
    try {
      await navigator.clipboard.writeText(text);
      pushToast?.('ok', msg);
    } catch {
      pushToast?.('err', '复制失败，请手动选择文本');
    }
  };

  const riskSorted = [...risk].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity) || b.count - a.count,
  );
  const shown = showAll ? riskSorted : riskSorted.slice(0, 8);

  return (
    <section className="card signals-card">
      <div className="risk-head">
        <div className="risk-head-title">
          <ShieldAlert size={15} />
          <b>{title}</b>
          <span className="form-hint">
            {total === 0
              ? '本次材料未命中任何关键词（未命中 ≠ 无风险）'
              : `命中 ${total} 项：风险 ${risk.length} ｜ 利好 ${growth.length} ｜ 刷量 ${volume.length + rules.length}`}
            {sum?.paths ? ` ｜ 检索 ${sum.paths} 路` : ''}
            {sum?.fetch ? ` ｜ 抓取 新${sum.fetch.new}/缓存${sum.fetch.cached}` : ''}
          </span>
        </div>
        <div className="risk-head-actions">
          {risk.length > 8 && (
            <button className="btn btn-ghost btn-sm" onClick={() => setShowAll(s => !s)}>
              {showAll ? '收起' : `全部 ${risk.length} 项`}
            </button>
          )}
          <button className="btn btn-ghost btn-sm" onClick={() => setOpen(o => !o)}>{open ? '收起' : '展开'}</button>
        </div>
      </div>

      {open && (
        <>
          {risk.length > 0 && (
            <div className="sig-group">
              <div className="risk-group-title">
                <AlertTriangle size={13} /> 公司风险关键词（命中即标注，不让高风险岗位进推荐位）
              </div>
              <div className="risk-counts">
                {SEVERITY_ORDER.map(s => {
                  const n = risk.filter(r => r.severity === s).length;
                  return n > 0 ? <span key={s} className={`risk-chip sev-${s}`}>{SEVERITY_LABEL[s]} {n}</span> : null;
                })}
              </div>
              <div className="sig-list">
                {shown.map(r => (
                  <div className={`sig-item sev-${r.severity}`} key={`${r.keyword}-${r.dimension}`}>
                    <span className={`risk-chip sev-${r.severity}`}>{SEVERITY_LABEL[r.severity]}</span>
                    <b>{r.keyword}</b>
                    <span className="sig-meta">×{r.count} ｜ {r.dimension}</span>
                    <div className="sig-snippet">{r.meaning}</div>
                    {r.snippet && <div className="sig-quote">{r.snippet}</div>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {growth.length > 0 && (
            <div className="sig-group">
              <div className="risk-group-title"><TrendingUp size={13} /> 扩张利好信号（融资 / 上市 / 扩产 / 技术突破 / 中标）</div>
              <div className="sig-chips">
                {growth.map(g => (
                  <span className="sig-tag" key={`${g.keyword}-${g.type}`} title={g.snippet}>
                    <b>{g.keyword}</b>×{g.count}
                    <i>{g.type}·{g.strength}</i>
                  </span>
                ))}
              </div>
            </div>
          )}

          {(volume.length > 0 || rules.length > 0) && (
            <div className="sig-group">
              <div className="risk-group-title"><Minus size={13} /> 刷量 / 虚假招聘线索</div>
              <div className="sig-chips">
                {volume.map(v => (
                  <span className="sig-tag" key={`${v.keyword}-${v.signal}`}><b>{v.keyword}</b>×{v.count}<i>{v.signal}·{v.strength}</i></span>
                ))}
              </div>
              {rules.map(r => (
                <div className="sig-item sev-medium" key={r.signal + r.subject}>
                  <span className="risk-chip sev-medium">{r.signal}</span>
                  <b>{r.subject}</b>
                  <div className="sig-snippet">{r.detail}</div>
                </div>
              ))}
            </div>
          )}

          {policies.length > 0 && (
            <div className="sig-group">
              <div className="risk-group-title">
                <Landmark size={13} /> 政策与产业规划检索路（原文比转述可靠：发改委 / 工信部 / 省政府规划专栏）
                <button className="btn btn-ghost btn-sm" onClick={() => copy(policies.join('\n'), '已复制政策检索关键词')}>
                  <ClipboardCopy size={12} /> 复制
                </button>
              </div>
              <div className="sig-chips">
                {policies.map(q => <span className="sig-tag" key={q}>{q}</span>)}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
