import { useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { X } from 'lucide-react';

// 空格 / 逗号 / 顿号 / 分号 / 竖线均视为分隔符，序列化回空格分隔字符串（与工作流输入格式一致）
const SEP = /[\s,，、;；|]+/;

interface Props {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  /** 常用选项：从下拉直接添加；手动输入始终保留 */
  presets?: string[];
}

export default function ChipInput({ value, onChange, placeholder, presets }: Props) {
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const items = value.split(SEP).filter(Boolean);

  const add = (raw: string) => {
    const parts = raw.split(SEP).filter(Boolean);
    if (!parts.length) return;
    onChange([...new Set([...items, ...parts])].join(' '));
  };

  const commit = () => {
    if (!draft.trim()) return;
    add(draft);
    setDraft('');
  };

  const remove = (i: number) => onChange(items.filter((_, idx) => idx !== i).join(' '));

  const onKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commit();
    } else if (e.key === 'Backspace' && !draft && items.length) {
      remove(items.length - 1);
    }
  };

  const available = (presets ?? []).filter(p => !items.includes(p));

  return (
    <div className="chips" onClick={() => inputRef.current?.focus()}>
      {items.map((it, i) => (
        <span className="chip" key={`${it}-${i}`}>
          {it}
          {/* onMouseDown 阻止默认行为，避免先触发输入框 blur 提交导致本次点击拿到过期数据 */}
          <button
            type="button"
            className="chip-x"
            aria-label={`删除 ${it}`}
            onMouseDown={e => e.preventDefault()}
            onClick={() => remove(i)}
          >
            <X size={12} />
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        className="chip-input"
        value={draft}
        placeholder={items.length ? '' : placeholder}
        onChange={e => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={commit}
      />
      {presets && presets.length > 0 && (
        <select
          className="chip-preset"
          value=""
          title="从常用选项添加（仍可手动输入）"
          onClick={e => e.stopPropagation()}
          onChange={e => {
            if (e.target.value) add(e.target.value);
            e.currentTarget.value = '';
          }}
        >
          <option value="">＋ 常用（{available.length}）</option>
          {available.map(p => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      )}
    </div>
  );
}
