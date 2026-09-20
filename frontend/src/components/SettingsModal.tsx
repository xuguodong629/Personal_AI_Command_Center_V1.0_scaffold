import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { testApp, type DifyConfig, type TestResult } from '../lib/dify';
import ModelsSettings from './ModelsSettings';

interface Props {
  open: boolean;
  cfg: DifyConfig;
  onSave: (c: DifyConfig) => void;
  onClose: () => void;
}

type Tab = 'dify' | 'models';

type AppId = 'radar' | 'bg' | 'resume';

const APPS: Array<{ id: AppId; label: string; field: keyof DifyConfig }> = [
  { id: 'radar', label: '岗位雷达', field: 'radarKey' },
  { id: 'bg', label: '公司背调', field: 'bgKey' },
  { id: 'resume', label: 'AI 猎头中枢', field: 'resumeKey' },
];

export default function SettingsModal({ open, cfg, onSave, onClose }: Props) {
  // V0.3：默认打开「模型直连」（独立运行）；Dify 工作流仅作为可选旧引擎
  const [tab, setTab] = useState<Tab>('models');
  const [draft, setDraft] = useState<DifyConfig>(cfg);
  const [testing, setTesting] = useState<AppId | null>(null);
  const [testOut, setTestOut] = useState<Partial<Record<AppId, TestResult>>>({});

  useEffect(() => {
    if (open) {
      setDraft(cfg);
      setTestOut({});
      setTab('models');
    }
  }, [open, cfg]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const set = (patch: Partial<DifyConfig>) => setDraft({ ...draft, ...patch });
  const missing = APPS.filter(a => !String(draft[a.field]).trim()).length;

  const runTest = async (app: (typeof APPS)[number]) => {
    const key = String(draft[app.field]).trim();
    if (!key) {
      setTestOut(s => ({ ...s, [app.id]: { ok: false, msg: '请先填写该工作流的 API Key' } }));
      return;
    }
    setTesting(app.id);
    const r = await testApp(draft.baseUrl, key);
    setTestOut(s => ({ ...s, [app.id]: r }));
    setTesting(null);
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="dialog dialog-lg" onClick={e => e.stopPropagation()}>
        <header className="dialog-head">
          <h3>设置</h3>
          <button className="iconbtn" onClick={onClose} title="关闭（Esc）">
            <X size={16} />
          </button>
        </header>

        <div className="settings-tabs">
          <button className={`settings-tab${tab === 'models' ? ' active' : ''}`} onClick={() => setTab('models')}>
            模型直连（推荐）
          </button>
          <button className={`settings-tab${tab === 'dify' ? ' active' : ''}`} onClick={() => setTab('dify')}>
            Dify 工作流（可选）
          </button>
        </div>

        <div className="dialog-body">
          {tab === 'dify' && (
            <>
              <div className="field">
                <label>Dify 服务地址（本地自部署，不含 /v1）</label>
                <input
                  className="input"
                  value={draft.baseUrl}
                  onChange={e => set({ baseUrl: e.target.value })}
                  placeholder="http://localhost"
                />
              </div>

              {APPS.map(app => (
                <div className="field" key={app.id}>
                  <div className="field-row">
                    <label>{app.label} API Key</label>
                    <button className="btn btn-ghost btn-sm" onClick={() => runTest(app)} disabled={testing !== null}>
                      {testing === app.id ? '测试中…' : '测试连接'}
                    </button>
                  </div>
                  <input
                    className="input"
                    type="password"
                    value={String(draft[app.field])}
                    onChange={e => set({ [app.field]: e.target.value } as Partial<DifyConfig>)}
                    placeholder="sk-..."
                  />
                  {testOut[app.id] && (
                    <p className={`test-out ${testOut[app.id]!.ok ? 'test-ok' : 'test-err'}`}>
                      {testOut[app.id]!.msg}
                    </p>
                  )}
                </div>
              ))}

              <p className="dialog-hint">
                可选：仅在需要使用自建 Dify 工作流时填写。密钥仅保存在本机浏览器 localStorage，不会上传。{missing > 0 && `还有 ${missing} 个 Key 未填写，对应工作流将无法运行。`}
                「测试连接」会读取该应用开始节点的输入变量名——如果与本页发送的变量名不一致，Dify 会静默丢弃输入导致空结果。
              </p>
            </>
          )}

          {tab === 'models' && <ModelsSettings />}
        </div>

        {tab === 'dify' && (
          <footer className="dialog-foot">
            <button className="btn btn-ghost" onClick={onClose}>取消</button>
            <button
              className="btn btn-primary"
              onClick={() => {
                onSave({ ...draft, baseUrl: draft.baseUrl.trim().replace(/\/+$/, '') });
                onClose();
              }}
            >
              保存配置
            </button>
          </footer>
        )}
      </div>
    </div>
  );
}
