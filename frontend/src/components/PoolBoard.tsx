import { useMemo, useState } from 'react';
import {
  ChevronDown, ChevronRight, Download, ExternalLink, LayoutGrid, ListFilter, Search, Table2,
} from 'lucide-react';
import { openExternal } from '../lib/backend';
import { downloadText } from '../lib/utils';
import {
  cleanCompany, field, isJunk, parseLevel, salaryValue, scoreValue, toCsv,
  type PoolItem,
} from '../lib/pool';

interface Props {
  items: PoolItem[];
  title?: string;
  pushToast: (kind: 'ok' | 'err' | 'info', msg: string) => void;
}

type View = 'card' | 'table';
type SortKey = 'level' | 'score' | 'salary';

const LEVEL_OPTIONS: Array<{ id: string; label: string; test: (l: string) => boolean }> = [
  { id: 'all', label: '全部', test: () => true },
  { id: 'high', label: '只看高', test: l => l.startsWith('高') },
  { id: 'hm', label: '高+中', test: l => l.startsWith('高') || l.startsWith('中') },
  { id: 'risk', label: '仅风险/刷量', test: l => /⚠️/.test(l) },
];

/** 机会池面板：卡片（默认）或紧凑表格；带排序/筛选/搜索/导出。
 *  设计目标：把 14 列原始表格变成「一眼能扫、点开能看细节」的列表。 */
export default function PoolBoard({ items, title = '机会池', pushToast }: Props) {
  const [view, setView] = useState<View>('card');
  const [sort, setSort] = useState<SortKey>('level');
  const [levelFilter, setLevelFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [hideJunk, setHideJunk] = useState(true);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  const rows = useMemo(() => {
    const opt = LEVEL_OPTIONS.find(o => o.id === levelFilter) || LEVEL_OPTIONS[0];
    const q = query.trim().toLowerCase();
    const list = items
      .map((it, i) => ({ it, i, lv: parseLevel(field(it, '级')) }))
      .filter(({ it, lv }) => opt.test(field(it, '级')) || (levelFilter === 'risk' && lv.flags.length > 0))
      .filter(({ it }) => !q || JSON.stringify(it).toLowerCase().includes(q))
      .filter(({ it }) => !hideJunk || !(isJunk(cleanCompany(it)) && isJunk(field(it, 'JD'))));
    list.sort((a, b) => {
      if (sort === 'score') return scoreValue(b.it) - scoreValue(a.it);
      if (sort === 'salary') return salaryValue(field(b.it, '薪资')) - salaryValue(field(a.it, '薪资'));
      return b.lv.rank - a.lv.rank || scoreValue(b.it) - scoreValue(a.it);
    });
    return list;
  }, [items, sort, levelFilter, query, hideJunk]);

  if (!items.length) return null;

  const stats = {
    total: items.length,
    high: items.filter(it => field(it, '级').startsWith('高')).length,
    mid: items.filter(it => field(it, '级').startsWith('中')).length,
    low: items.filter(it => field(it, '级').startsWith('低')).length,
    risk: items.filter(it => /⚠️/.test(field(it, '级')) || /⚠️/.test(field(it, '风险标记'))).length,
  };

  const open = async (target: string) => {
    const url = (target || '').match(/https?:\/\/\S+/)?.[0];
    if (!url) {
      pushToast('info', '该条目没有直接链接（材料未返回 url），请用平台站内检索');
      return;
    }
    const r = await openExternal(url);
    if (!r.ok) pushToast('err', r.error);
  };

  const linkOf = (it: PoolItem): string => {
    const raw = `${field(it, '链接')} ${field(it, 'JD')} ${field(it, '来源平台')}`;
    const m = raw.match(/https?:\/\/\S+/);
    return m ? m[0].replace(/[）)]+$/, '') : '';
  };

  return (
    <section className="card pool-board">
      <div className="pool-head">
        <div className="pool-head-left">
          <LayoutGrid size={15} />
          <b>{title}</b>
          <span className="form-hint">
            共 {stats.total} 条 ｜ 高 {stats.high} · 中 {stats.mid} · 低 {stats.low}
            {stats.risk ? ` · 带风险标记 ${stats.risk}` : ''}
          </span>
        </div>
        <div className="pool-head-right">
          <div className="pool-seg">
            <button className={`pool-seg-btn ${view === 'card' ? 'on' : ''}`} onClick={() => setView('card')} title="卡片视图">
              <LayoutGrid size={13} /> 卡片
            </button>
            <button className={`pool-seg-btn ${view === 'table' ? 'on' : ''}`} onClick={() => setView('table')} title="紧凑表格">
              <Table2 size={13} /> 表格
            </button>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => downloadText(`机会池-${Date.now()}.csv`, toCsv(items))}>
            <Download size={13} /> CSV
          </button>
        </div>
      </div>

      <div className="pool-tools">
        <div className="pool-search">
          <Search size={13} />
          <input value={query} onChange={e => setQuery(e.target.value)} placeholder="搜公司 / 岗位 / 地区 / 风险关键词" />
        </div>
        <div className="pool-seg">
          {LEVEL_OPTIONS.map(o => (
            <button key={o.id} className={`pool-seg-btn ${levelFilter === o.id ? 'on' : ''}`} onClick={() => setLevelFilter(o.id)}>
              {o.label}
            </button>
          ))}
        </div>
        <label className="check">
          <ListFilter size={12} />
          <select className="input select-inline" value={sort} onChange={e => setSort(e.target.value as SortKey)}>
            <option value="level">按推荐级排序</option>
            <option value="score">按加权总分排序</option>
            <option value="salary">按薪资排序</option>
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={hideJunk} onChange={e => setHideJunk(e.target.checked)} />
          隐藏信息缺失行
        </label>
      </div>

      {view === 'card' && (
        <div className="pool-cards">
          {rows.map(({ it, i, lv }) => {
            const salary = field(it, '薪资');
            const welfare = field(it, '福利保障');
            const riskMark = field(it, '风险标记');
            const jd = field(it, 'JD');
            const link = linkOf(it);
            const exp = field(it, '经验', '学历');
            const published = field(it, '发布时间');
            const platform = field(it, '来源平台');
            const region = field(it, '地区');
            const open2 = !!expanded[i];
            return (
              <article className={`pool-card tone-${lv.tone}`} key={`${cleanCompany(it)}-${field(it, '岗位')}-${i}`}>
                <div className="pool-card-main">
                  <div className={`pool-lv lv-${lv.tone}`}>
                    <b>{lv.level}</b>
                    {lv.note && <span>{lv.note}</span>}
                  </div>
                  <div className="pool-card-body">
                    <div className="pool-card-title">
                      <h4>{field(it, '岗位')}</h4>
                      <span className="pool-company">{cleanCompany(it)}</span>
                      {scoreValue(it) >= 0 && (
                        <span className={`pool-score ${field(it, '_layer').includes('优先') ? 'good' : ''}`}>
                          {scoreValue(it)} 分{field(it, '_layer') ? ` · ${field(it, '_layer')}` : ''}
                        </span>
                      )}
                    </div>
                    <div className="pool-chips">
                      {!isJunk(region) && <span className="pool-chip">{region}</span>}
                      {!isJunk(salary) && <span className="pool-chip salary">{salary}</span>}
                      {!isJunk(exp) && <span className="pool-chip">{exp}</span>}
                      {!isJunk(welfare) && <span className="pool-chip soft">{welfare}</span>}
                      {!isJunk(published) && <span className="pool-chip">{published}</span>}
                      {!isJunk(platform) && <span className="pool-chip soft">{platform}</span>}
                    </div>
                    {riskMark && !isJunk(riskMark) && (
                      <div className={`pool-risk ${/⚠️|一票否决|刷量|失信|欠薪|收费/.test(riskMark) ? 'severe' : ''}`}>
                        ⚠️ {riskMark}
                      </div>
                    )}
                    {jd && !isJunk(jd) && (
                      <p className={`pool-jd ${open2 ? 'open' : ''}`}>{jd}</p>
                    )}
                  </div>
                  <div className="pool-card-actions">
                    {link && (
                      <button className="btn btn-ghost btn-sm" onClick={() => open(link)} title={link}>
                        <ExternalLink size={13} /> 打开
                      </button>
                    )}
                    <button className="btn btn-ghost btn-sm" onClick={() => setExpanded(s => ({ ...s, [i]: !s[i] }))}>
                      {open2 ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      {open2 ? '收起' : '详情'}
                    </button>
                  </div>
                </div>
                {open2 && (
                  <div className="pool-detail">
                    {field(it, '公司性质') && <div><i>公司性质</i>{field(it, '公司性质')}</div>}
                    {field(it, '公司规模') && <div><i>公司规模</i>{field(it, '公司规模')}</div>}
                    <div><i>JD 要点</i>{jd || '材料未见'}</div>
                    <div><i>风险标记</i>{riskMark || '未命中'}</div>
                    <div><i>链接/来源</i>{link || '材料未返回 url，需站内检索'}（{platform || '平台未见'}）</div>
                  </div>
                )}
              </article>
            );
          })}
          {rows.length === 0 && <div className="form-hint">当前筛选下没有条目（试试取消筛选或减少隐藏条件）。</div>}
        </div>
      )}

      {view === 'table' && (
        <div className="pool-table-wrap">
          <table className="pool-table">
            <thead>
              <tr>
                <th>级</th><th>岗位</th><th>公司</th><th>地区</th><th>薪资</th>
                <th>总分</th><th>风险标记</th><th>平台</th><th>链接</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ it, i, lv }) => (
                <tr key={`${cleanCompany(it)}-${i}`} className={`tone-${lv.tone}`}>
                  <td><span className={`pool-lv-inline lv-${lv.tone}`}>{field(it, '级')}</span></td>
                  <td className="nowrap-cell">{field(it, '岗位')}</td>
                  <td>{cleanCompany(it)}</td>
                  <td>{field(it, '地区')}</td>
                  <td>{field(it, '薪资')}</td>
                  <td>{scoreValue(it) >= 0 ? scoreValue(it) : '—'}</td>
                  <td className="risk-cell">{field(it, '风险标记') || '—'}</td>
                  <td>{field(it, '来源平台')}</td>
                  <td>
                    {linkOf(it)
                      ? <button className="link-btn" onClick={() => open(linkOf(it))}>打开</button>
                      : <span className="form-hint">站内检索</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <div className="form-hint">当前筛选下没有条目。</div>}
        </div>
      )}
    </section>
  );
}
