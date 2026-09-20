import { useEffect, useMemo, useRef, useState } from 'react';
import type { ComponentType, KeyboardEvent as ReactKeyboardEvent } from 'react';

export interface PaletteAction {
  id: string;
  label: string;
  hint?: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  run: () => void;
}

interface Props {
  open: boolean;
  actions: PaletteAction[];
  onClose: () => void;
}

export default function CommandPalette({ open, actions, onClose }: Props) {
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery('');
      setIndex(0);
      // 等挂载后聚焦
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Esc 关闭：挂在 window 上，避免点过列表项后焦点不在输入框时按 Esc 无效
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    return actions.filter(a =>
      a.label.toLowerCase().includes(q) || (a.hint ?? '').toLowerCase().includes(q),
    );
  }, [actions, query]);

  if (!open) return null;

  const clamp = (i: number) => Math.max(0, Math.min(i, filtered.length - 1));

  const onKeyDown = (e: ReactKeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setIndex(i => clamp(i + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setIndex(i => clamp(i - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const act = filtered[index];
      if (act) {
        act.run();
        onClose();
      }
    }
  };

  return (
    <div className="overlay palette-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label="命令面板">
      <div className="palette" onClick={e => e.stopPropagation()}>
        <div className="palette-search">
          <span className="palette-glyph">⌘</span>
          <input
            ref={inputRef}
            value={query}
            placeholder="输入命令，回车执行…"
            onChange={e => {
              setQuery(e.target.value);
              setIndex(0);
            }}
            onKeyDown={onKeyDown}
          />
          <span className="kbd">Esc</span>
        </div>
        <div className="plist">
          {filtered.length === 0 && <div className="pempty">没有匹配的命令</div>}
          {filtered.map((a, i) => {
            const Icon = a.icon;
            return (
              <div
                key={a.id}
                className={`pitem${i === index ? ' active' : ''}`}
                onMouseEnter={() => setIndex(i)}
                onClick={() => {
                  a.run();
                  onClose();
                }}
              >
                <Icon size={15} />
                <span>{a.label}</span>
                {a.hint && <span className="kbd">{a.hint}</span>}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
