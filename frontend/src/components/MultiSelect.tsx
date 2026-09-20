import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, ChevronDown } from 'lucide-react';

export interface MSOption {
  value: string;
  label: string;
  /** 分组名（照搬招聘网站的分组展示，如「豫北」「家电整机」） */
  group?: string;
}

interface Props {
  options: MSOption[];
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  /** 允许自定义输入（回车添加），默认关闭 */
  allowCustom?: boolean;
  /** 触发器上最多显示几个已选项 */
  maxChips?: number;
}

/** 下拉多选：分组展示 + 搜索 + 全选/反选/清空 + 自定义输入（对齐招聘网站的筛选交互） */
export default function MultiSelect({ options, value, onChange, placeholder = '请选择', allowCustom, maxChips = 2 }: Props) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [custom, setCustom] = useState('');
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const shown = useMemo(() => {
    const kw = q.trim().toLowerCase();
    return kw ? options.filter(o => o.label.toLowerCase().includes(kw) || o.value.toLowerCase().includes(kw)) : options;
  }, [options, q]);

  // 按 group 保序分组（无 group 的归入「其他」前的默认组）
  const grouped = useMemo(() => {
    const map = new Map<string, MSOption[]>();
    for (const o of shown) {
      const g = o.group || '';
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(o);
    }
    return [...map.entries()];
  }, [shown]);

  const toggle = (v: string) => onChange(value.includes(v) ? value.filter(x => x !== v) : [...value, v]);

  const selectAllShown = () => onChange([...new Set([...value, ...shown.map(o => o.value)])]);
  const invertShown = () => {
    const shownSet = new Set(shown.map(o => o.value));
    const kept = value.filter(v => !shownSet.has(v));
    const added = shown.filter(o => !value.includes(o.value)).map(o => o.value);
    onChange([...kept, ...added]);
  };

  const addCustom = () => {
    const parts = custom.split(/[\s,，、;；|]+/).filter(Boolean);
    if (parts.length) onChange([...new Set([...value, ...parts])]);
    setCustom('');
  };

  const labelOf = (v: string) => options.find(o => o.value === v)?.label ?? v;

  return (
    <div className="ms" ref={boxRef}>
      <button
        type="button"
        className={`ms-trigger${open ? ' open' : ''}`}
        onClick={() => setOpen(o => !o)}
        title={value.length ? value.map(labelOf).join('、') : placeholder}
      >
        <span className="ms-value">
          {value.length === 0 ? (
            <span className="ms-ph">{placeholder}</span>
          ) : (
            <>
              {value.slice(0, maxChips).map(v => (
                <span className="ms-chip" key={v}>
                  {labelOf(v)}
                  <i
                    role="presentation"
                    onMouseDown={e => e.preventDefault()}
                    onClick={e => {
                      e.stopPropagation();
                      toggle(v);
                    }}
                  >
                    ×
                  </i>
                </span>
              ))}
              {value.length > maxChips && <span className="ms-more">+{value.length - maxChips}</span>}
            </>
          )}
        </span>
        <ChevronDown size={14} />
      </button>

      {open && (
        <div className="ms-panel">
          <input className="input ms-search" value={q} onChange={e => setQ(e.target.value)} placeholder="搜索选项…" autoFocus />
          <div className="ms-tools">
            <button type="button" className="link-btn" onClick={selectAllShown}>全选</button>
            <span className="ms-sep">·</span>
            <button type="button" className="link-btn" onClick={invertShown}>反选</button>
            <span className="ms-sep">·</span>
            <button type="button" className="link-btn" onClick={() => onChange([])}>清空</button>
            <span className="flex-spacer" />
            <span className="ms-count">已选 {value.length} / {options.length}</span>
          </div>
          <div className="ms-list">
            {shown.length === 0 && <div className="ms-empty">无匹配选项</div>}
            {grouped.map(([group, items]) => (
              <div className="ms-group" key={group || '_'}>
                {group && <div className="ms-group-head">{group}</div>}
                {items.map(o => {
                  const on = value.includes(o.value);
                  return (
                    <button key={o.value} type="button" className={`ms-opt${on ? ' on' : ''}`} onClick={() => toggle(o.value)}>
                      <span className="ms-box">{on && <Check size={12} />}</span>
                      {o.label}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
          {allowCustom && (
            <input
              className="input ms-search"
              value={custom}
              onChange={e => setCustom(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addCustom();
                }
              }}
              placeholder="自定义输入，回车添加"
            />
          )}
          <div className="ms-foot">
            <span className="ms-count">已选 {value.length} 项</span>
            <span className="flex-spacer" />
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>完成</button>
          </div>
        </div>
      )}
    </div>
  );
}
