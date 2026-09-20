import { AlertCircle, CheckCircle2, Info } from 'lucide-react';

export interface ToastItem {
  id: string;
  kind: 'ok' | 'err' | 'info';
  msg: string;
}

const ICONS = {
  ok: <CheckCircle2 size={15} />,
  err: <AlertCircle size={15} />,
  info: <Info size={15} />,
};

export default function Toasts({ items }: { items: ToastItem[] }) {
  if (!items.length) return null;
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map(t => (
        <div key={t.id} className={`toast toast-${t.kind}`}>
          {ICONS[t.kind]}
          <span>{t.msg}</span>
        </div>
      ))}
    </div>
  );
}
