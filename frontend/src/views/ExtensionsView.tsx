import { useEffect, useState } from 'react';
import { Blocks, Plus, RefreshCw, Save, Sparkles, Trash2, Wrench } from 'lucide-react';
import ResultPanel from '../components/ResultPanel';
import { useProviders } from '../lib/useProviders';
import {
  MCP_PRESETS,
  deleteServer,
  deleteSkill,
  getSkill,
  importSkill,
  listServers,
  listSkills,
  listTools,
  runSkill,
  saveServers,
  saveSkill,
  testServer,
  type McpServer,
  type McpTool,
  type SkillSummary,
} from '../lib/extensions';

interface Props {
  settingsOpen: boolean;
  openSettings: () => void;
  pushToast: (kind: 'ok' | 'err' | 'info', msg: string) => void;
}

/** 扩展中心：MCP 服务器（成熟外部模块）+ 技能（Skills） */
export default function ExtensionsView({ settingsOpen, openSettings, pushToast }: Props) {
  const [tab, setTab] = useState<'mcp' | 'skills'>('mcp');
  const { providerId } = useProviders(settingsOpen);

  /* ---------- MCP ---------- */
  const [servers, setServers] = useState<McpServer[]>([]);
  const [tools, setTools] = useState<McpTool[]>([]);
  const [toolErrors, setToolErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [presetIdx, setPresetIdx] = useState(0);
  const [callOut, setCallOut] = useState('');
  const [testOut, setTestOut] = useState<Record<string, string>>({});

  /* ---------- Skills ---------- */
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [skillName, setSkillName] = useState('');
  const [skillContent, setSkillContent] = useState('');
  const [skillInput, setSkillInput] = useState('');
  const [skillContext, setSkillContext] = useState('');
  const [skillResult, setSkillResult] = useState('');
  const [importUrl, setImportUrl] = useState('');

  const loadMcp = async () => {
    const r = await listServers();
    if (r.ok) setServers(r.servers);
    else setToolErrors([r.error]);
  };
  const loadSkills = async () => {
    const r = await listSkills();
    if (r.ok) setSkills(r.skills);
  };

  useEffect(() => {
    void loadMcp();
    void loadSkills();
  }, []);

  /* ---------- MCP 操作 ---------- */

  const patch = (id: string, p: Partial<McpServer>) => {
    setServers(list => list.map(s => (s.id === id ? { ...s, ...p } : s)));
    setDirty(true);
  };

  const addPreset = () => {
    const p = MCP_PRESETS[presetIdx];
    const id = `m${Date.now().toString(36)}`;
    setServers(list => [
      ...list,
      { ...p.server, id, enabled: true, auto_approve: false },
    ]);
    setDirty(true);
    pushToast('info', `已添加「${p.server.name}」，记得保存后测试`);
  };

  const persist = async () => {
    setBusy(true);
    try {
      const r = await saveServers(servers);
      if (!r.ok) {
        pushToast('err', `保存失败：${r.error}`);
        return;
      }
      setDirty(false);
      pushToast('ok', 'MCP 配置已保存');
      await loadMcp();
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm('删除这个 MCP 服务器配置？')) return;
    const r = await deleteServer(id);
    if (!r.ok) {
      pushToast('err', `删除失败：${r.error}`);
      return;
    }
    await loadMcp();
    pushToast('ok', '已删除');
  };

  const doTest = async (id: string) => {
    setTestOut(o => ({ ...o, [id]: '测试中（首次运行会下载依赖，可能较慢）…' }));
    const r = await testServer(id);
    setTestOut(o => ({
      ...o,
      [id]: r.ok
        ? `✅ 连接成功（${r.latency_ms} ms）· 工具 ${r.tools.length} 个：${r.tools.map(t => t.name).slice(0, 8).join('、')}`
        : `❌ ${r.error}`,
    }));
    if (r.ok) void refreshTools();
  };

  const refreshTools = async () => {
    setBusy(true);
    try {
      const r = await listTools(true);
      if (!r.ok) {
        pushToast('err', `获取工具失败：${r.error}`);
        return;
      }
      setTools(r.tools);
      setToolErrors(r.errors);
    } finally {
      setBusy(false);
    }
  };

  const tryCall = async (t: McpTool) => {
    const raw = window.prompt(`调用 ${t.tool} 的参数（JSON）`, '{}');
    if (raw === null) return;
    let args: Record<string, unknown> = {};
    try {
      args = JSON.parse(raw || '{}') as Record<string, unknown>;
    } catch {
      pushToast('err', '参数不是合法 JSON');
      return;
    }
    const r = await callToolSafe(t.server_id, t.tool, args);
    setCallOut(r);
  };

  const callToolSafe = async (sid: string, tool: string, args: Record<string, unknown>) => {
    const { callTool } = await import('../lib/extensions');
    const r = await callTool(sid, tool, args);
    return r.ok ? `✅ ${tool}\n\n${r.content}` : `❌ ${r.error}`;
  };

  /* ---------- Skills 操作 ---------- */

  const openSkill = async (name: string) => {
    const r = await getSkill(name);
    if (!r.ok) {
      pushToast('err', `读取失败：${r.error}`);
      return;
    }
    setSkillName(r.skill.name);
    setSkillContent(r.skill.content);
    setSkillResult('');
  };

  const newSkill = () => {
    setSkillName('');
    setSkillContent('---\ntitle: 新技能\ndescription: 一句话说明用途\n---\n\n你是……请……\n\n要求：全程中文；只依据给定内容，不得编造。');
    setSkillResult('');
  };

  const persistSkill = async () => {
    if (!skillName.trim()) {
      pushToast('err', '请填技能名（英文/数字/- _）');
      return;
    }
    const r = await saveSkill(skillName.trim(), skillContent);
    if (!r.ok) {
      pushToast('err', `保存失败：${r.error}`);
      return;
    }
    pushToast('ok', '技能已保存');
    await loadSkills();
  };

  const removeSkill = async (name: string) => {
    if (!window.confirm(`删除技能「${name}」？`)) return;
    const r = await deleteSkill(name);
    if (!r.ok) {
      pushToast('err', `删除失败：${r.error}`);
      return;
    }
    await loadSkills();
    pushToast('ok', '已删除');
  };

  const doImport = async () => {
    if (!importUrl.trim()) return;
    const r = await importSkill(importUrl.trim());
    if (!r.ok) {
      pushToast('err', `导入失败：${r.error}`);
      return;
    }
    pushToast('ok', `已导入：${r.title}`);
    setImportUrl('');
    await loadSkills();
  };

  const doRun = async () => {
    if (!providerId) {
      openSettings();
      pushToast('err', '请先在设置里选择模型');
      return;
    }
    if (!skillName) {
      pushToast('err', '请先选择或新建技能');
      return;
    }
    setBusy(true);
    try {
      const r = await runSkill(skillName, providerId, skillInput, skillContext);
      if (!r.ok) {
        pushToast('err', `执行失败：${r.error}`);
        return;
      }
      setSkillResult(r.content);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view">
      <header className="view-head">
        <h2>扩展中心</h2>
        <p>接入成熟的 MCP 服务器（文件系统 / 抓取 / SQLite / Git / 浏览器…），并把常用方法论沉淀成技能，按需调用。</p>
      </header>

      <div className="settings-tabs" style={{ padding: '0 0 0', borderBottom: '1px solid var(--border)', marginBottom: 12 }}>
        <button className={`settings-tab${tab === 'mcp' ? ' active' : ''}`} onClick={() => setTab('mcp')}>
          MCP 服务器
        </button>
        <button className={`settings-tab${tab === 'skills' ? ' active' : ''}`} onClick={() => setTab('skills')}>
          技能（Skills）
        </button>
      </div>

      {tab === 'mcp' && (
        <>
          <section className="card">
            <div className="filter-row">
              <span className="filter-title">MCP 服务器</span>
              <select className="input select-inline" value={presetIdx} onChange={e => setPresetIdx(Number(e.target.value))}>
                {MCP_PRESETS.map((p, i) => (
                  <option key={p.label} value={i}>{p.label}</option>
                ))}
              </select>
              <button className="btn btn-ghost btn-sm" onClick={addPreset}>
                <Plus size={13} /> 添加预设
              </button>
              <button className="btn btn-primary btn-sm" onClick={persist} disabled={busy || !dirty}>
                <Save size={13} /> {dirty ? '保存配置' : '已保存'}
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => void refreshTools()} disabled={busy}>
                <RefreshCw size={13} className={busy ? 'spin-once' : ''} /> 刷新工具清单
              </button>
              <span className="form-hint">stdio 服务器由后端用 npx/uvx 拉起；首次运行会联网下载依赖</span>
            </div>

            {servers.length === 0 && <p className="dialog-hint">还没有服务器：从上方预设里选一个「添加预设」，保存后点「测试」。</p>}

            {servers.map(s => (
              <div className="provider-card" key={s.id}>
                <div className="provider-grid">
                  <label>名称
                    <input className="input" value={s.name} onChange={e => patch(s.id, { name: e.target.value })} />
                  </label>
                  <label>传输方式
                    <select className="input" value={s.transport} onChange={e => patch(s.id, { transport: e.target.value as McpServer['transport'] })}>
                      <option value="stdio">stdio（后端拉起进程）</option>
                      <option value="http">http（连接已运行服务）</option>
                    </select>
                  </label>
                  {s.transport === 'stdio' ? (
                    <>
                      <label>命令
                        <input className="input" value={s.command} onChange={e => patch(s.id, { command: e.target.value })} placeholder="npx / uvx" />
                      </label>
                      <label>参数（空格分隔）
                        <input
                          className="input"
                          value={s.args.join(' ')}
                          onChange={e => patch(s.id, { args: e.target.value.split(/\s+/).filter(Boolean) })}
                          placeholder="-y @modelcontextprotocol/server-fetch"
                        />
                      </label>
                    </>
                  ) : (
                    <label>服务地址
                      <input className="input" value={s.url} onChange={e => patch(s.id, { url: e.target.value })} placeholder="http://127.0.0.1:3001/mcp" />
                    </label>
                  )}
                  <label>备注
                    <input className="input" value={s.note} onChange={e => patch(s.id, { note: e.target.value })} />
                  </label>
                  <label className="check">
                    <input type="checkbox" checked={s.enabled} onChange={e => patch(s.id, { enabled: e.target.checked })} />
                    启用（参与工具调用）
                  </label>
                  <label className="check">
                    <input type="checkbox" checked={s.auto_approve} onChange={e => patch(s.id, { auto_approve: e.target.checked })} />
                    免确认（高风险，谨慎）
                  </label>
                </div>
                <div className="provider-actions">
                  <button className="btn btn-ghost btn-sm" onClick={() => void doTest(s.id)}>
                    <Wrench size={13} /> 测试连接
                  </button>
                  <button className="btn btn-ghost btn-sm btn-danger" onClick={() => void remove(s.id)}>
                    <Trash2 size={13} /> 删除
                  </button>
                  <span className="form-hint">工具数：{s.tool_count ?? '未获取'}</span>
                </div>
                {testOut[s.id] && <p className="test-out test-ok">{testOut[s.id]}</p>}
              </div>
            ))}
          </section>

          <section className="card" style={{ marginTop: 12 }}>
            <div className="filter-row">
              <span className="filter-title">可用工具（{tools.length}）</span>
              <span className="form-hint">在「AI 助手」里打开「允许调用工具」后，模型会自行选择这些工具</span>
            </div>
            {toolErrors.length > 0 && <div className="banner banner-warn">{toolErrors.join('；')}</div>}
            {tools.map(t => (
              <div className="provider-card" key={t.full_name}>
                <b style={{ fontSize: 13 }}>{t.tool}</b>
                <span className="pill" style={{ marginLeft: 8 }}>{t.server_id}</span>
                <p className="dialog-hint">{t.description || '（无描述）'}</p>
                <div className="provider-actions">
                  <button className="btn btn-ghost btn-sm" onClick={() => void tryCall(t)}>
                    <Blocks size={13} /> 试调
                  </button>
                </div>
              </div>
            ))}
          </section>

          {callOut && <ResultPanel title="工具调用结果" text={callOut} badge="MCP" />}
        </>
      )}

      {tab === 'skills' && (
        <>
          <section className="card">
            <div className="filter-row">
              <span className="filter-title">技能库</span>
              <button className="btn btn-ghost btn-sm" onClick={newSkill}>
                <Plus size={13} /> 新建技能
              </button>
              <input className="input select-inline" value={importUrl} onChange={e => setImportUrl(e.target.value)} placeholder="从 URL 导入 SKILL.md" />
              <button className="btn btn-ghost btn-sm" onClick={() => void doImport()} disabled={!importUrl.trim()}>
                导入
              </button>
              <span className="form-hint">首次运行会自动生成 4 个内置技能（JD 拆解 / 简历润色 / 面试出题 / 情报简报）</span>
            </div>
            <div className="form-grid">
              {skills.map(s => (
                <div className="provider-card" key={s.name}>
                  <b style={{ fontSize: 13 }}>{s.title}</b>
                  <p className="dialog-hint">{s.description || s.name} · {s.chars} 字</p>
                  <div className="provider-actions">
                    <button className="btn btn-ghost btn-sm" onClick={() => void openSkill(s.name)}>编辑</button>
                    <button className="btn btn-ghost btn-sm btn-danger" onClick={() => void removeSkill(s.name)}>
                      <Trash2 size={13} /> 删除
                    </button>
                  </div>
                </div>
              ))}
              {skills.length === 0 && <p className="dialog-hint">还没有技能，点「新建技能」。</p>}
            </div>
          </section>

          <section className="card" style={{ marginTop: 12 }}>
            <div className="field">
              <label>技能名（英文/数字/-_）</label>
              <input className="input" value={skillName} onChange={e => setSkillName(e.target.value)} placeholder="jd-breakdown" />
            </div>
            <div className="field">
              <label>SKILL.md 内容（front-matter 可写 title / description）</label>
              <textarea className="input" rows={8} value={skillContent} onChange={e => setSkillContent(e.target.value)} />
            </div>
            <div className="form-actions">
              <button className="btn btn-primary" onClick={() => void persistSkill()}>保存技能</button>
            </div>
            <div className="field">
              <label>试运行：输入</label>
              <textarea className="input" rows={3} value={skillInput} onChange={e => setSkillInput(e.target.value)} placeholder="例如：把这段 JD 拆解一下……" />
            </div>
            <div className="field">
              <label>补充材料（可选，如 JD / 简历 / 资料）</label>
              <textarea className="input" rows={3} value={skillContext} onChange={e => setSkillContext(e.target.value)} />
            </div>
            <div className="form-actions">
              <button className="btn btn-primary" onClick={() => void doRun()} disabled={busy}>
                {busy ? <Sparkles size={15} className="spin-once" /> : <Sparkles size={15} />}
                {busy ? '执行中…' : '运行技能'}
              </button>
              <span className="form-hint">用当前选中的直连模型执行</span>
            </div>
          </section>

          {skillResult && <ResultPanel title="技能执行结果" text={skillResult} badge={skillName} />}
        </>
      )}
    </div>
  );
}
