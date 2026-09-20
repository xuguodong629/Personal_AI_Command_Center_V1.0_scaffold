import type { ModelProvider } from '../lib/backend';

export type Engine = 'dify' | 'direct';

interface Props {
  engine: Engine;
  onEngine: (e: Engine) => void;
  providers: ModelProvider[] | null;
  providerId: string;
  onProvider: (id: string) => void;
  openSettings: () => void;
  /** 直连模式下的说明，如"需联网搜索" */
  directHint?: string;
}

/** 模块级引擎切换：直连模型（默认，独立运行）/ Dify 工作流（可选，需自建） */
export default function EnginePicker({ engine, onEngine, providers, providerId, onProvider, openSettings, directHint }: Props) {
  return (
    <div className="engine-row">
      <div className="seg" role="tablist">
        <button
          type="button"
          className={`seg-btn${engine === 'direct' ? ' active' : ''}`}
          onClick={() => onEngine('direct')}
        >
          直连模型
        </button>
        <button
          type="button"
          className={`seg-btn${engine === 'dify' ? ' active' : ''}`}
          onClick={() => onEngine('dify')}
        >
          Dify 工作流（可选）
        </button>
      </div>
      {engine === 'direct' && (
        <>
          {providers === null ? (
            <span className="form-hint">读取模型配置中…</span>
          ) : providers.length === 0 ? (
            <button className="link-btn" onClick={openSettings}>还没有可用模型，去设置里添加 →</button>
          ) : (
            <select className="input select-inline" value={providerId} onChange={e => onProvider(e.target.value)}>
              {providers.map(p => (
                <option key={p.id} value={p.id}>{p.name} · {p.model}</option>
              ))}
            </select>
          )}
          {directHint && <span className="form-hint">{directHint}</span>}
        </>
      )}
    </div>
  );
}
