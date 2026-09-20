import { useEffect, useState } from 'react';
import { Loader2, Plus, Trash2 } from 'lucide-react';
import {
  fetchProviders, fetchSearchConfig, saveProviders, saveSearchConfig, testProvider, testSearch, PRESETS, SEARCH_ENGINES,
  type ModelProvider, type SearchConfig,
} from '../lib/backend';

function newId(): string {
  return `p_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

/** 设置弹窗里的「模型直连」标签页：供应商增删改 + 连接测试 */
export default function ModelsSettings() {
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [backendErr, setBackendErr] = useState('');
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState(0);
  const [presetIdx, setPresetIdx] = useState(0);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testOut, setTestOut] = useState<Record<string, { ok: boolean; msg: string }>>({});
  const [searchTest, setSearchTest] = useState<{ ok: boolean; msg: string } | null>(null);
  const [searchTesting, setSearchTesting] = useState(false);
  const [search, setSearch] = useState<SearchConfig>({
    engine: 'none',
    api_key: '',
    fallback_engine: 'none',
    fallback_api_key: '',
    searxng_url: 'http://127.0.0.1:8888',
    mcp_server_id: '',
    mcp_tool: '',
    mcp_query_arg: 'query',
    days: 0,
    max_results: 5,
    include_domains: '',
    exclude_domains: '',
    exclude_keywords: '',
    fetch_pages: true,
    fetch_limit: 4,
    fetcher: 'auto',
    skip_login_walls: true,
  });

  const patchSearch = (p: Partial<SearchConfig>) => {
    setSearch(s => ({ ...s, ...p }));
    setDirty(true);
  };

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchProviders(), fetchSearchConfig()]).then(([r, s]) => {
      if (!r.ok) {
        setBackendErr(r.error);
      } else if (r.providers) {
        setProviders(r.providers);
        setBackendErr('');
      } else {
        setBackendErr('后端返回格式异常');
      }
      if (s.ok && s.search) setSearch(s.search);
      setLoading(false);
    });
  }, []);

  const patch = (id: string, p: Partial<ModelProvider>) => {
    setProviders(list => list.map(x => (x.id === id ? { ...x, ...p } : x)));
    setDirty(true);
  };

  const add = () => {
    const preset = PRESETS[presetIdx];
    setProviders(list => [
      ...list,
      {
        id: newId(),
        name: preset.label,
        base_url: preset.base_url,
        api_key: '',
        model: preset.model,
      },
    ]);
    setDirty(true);
  };

  const remove = (id: string) => {
    setProviders(list => list.filter(x => x.id !== id));
    setDirty(true);
  };

  const save = async () => {
    const [r, sr] = await Promise.all([saveProviders(providers), saveSearchConfig(search)]);
    if (!r.ok) {
      setBackendErr(r.error);
    } else if (!sr.ok) {
      setBackendErr(sr.error);
    } else {
      setDirty(false);
      setSavedAt(Date.now());
      setTimeout(() => setSavedAt(0), 2000);
    }
  };

  const test = async (p: ModelProvider) => {
    if (!p.base_url.trim() || !p.model.trim()) {
      setTestOut(s => ({ ...s, [p.id]: { ok: false, msg: '请先填写 API 地址与模型名' } }));
      return;
    }
    setTestingId(p.id);
    const r = await testProvider({ base_url: p.base_url, api_key: p.api_key, model: p.model });
    setTestingId(null);
    setTestOut(s => ({
      ...s,
      [p.id]: r.ok ? { ok: true, msg: `连通正常（${r.latency_ms}ms）${r.reply ? ` · 模型回复：${r.reply}` : ''}` } : { ok: false, msg: r.error || '测试失败' },
    }));
  };

  return (
    <div className="models-settings">
      {backendErr && <div className="banner banner-warn">{backendErr}</div>}
      {loading && <p className="dialog-hint">读取配置中…</p>}

      {!loading && !backendErr && (
        <>
          <p className="dialog-hint">
            直连任何 OpenAI 兼容模型服务，不经 Dify。Key 保存在本机 data/config/ai.json。
            注意：智谱地址是 <code>https://open.bigmodel.cn/api/paas/v4</code>（不带 /v1）。
          </p>

          <div className="models-toolbar">
            <select
              className="input select-inline"
              value={presetIdx}
              onChange={e => setPresetIdx(Number(e.target.value))}
            >
              {PRESETS.map((p, i) => (
                <option key={p.label} value={i}>{p.label}</option>
              ))}
            </select>
            <button className="btn btn-ghost btn-sm" onClick={add}>
              <Plus size={13} /> 添加模型
            </button>
            <span className="flex-spacer" />
            {savedAt > 0 && <span className="saved-hint">已保存 ✓</span>}
            <button className="btn btn-primary btn-sm" onClick={save} disabled={!dirty}>
              {dirty ? '保存配置' : '已保存'}
            </button>
          </div>

          {providers.length === 0 && (
            <p className="dialog-hint">还没有添加模型服务，选择上方预设后点「添加模型」。</p>
          )}

          {providers.map(p => (
            <div className="provider-card" key={p.id}>
              <div className="provider-grid">
                <label>名称
                  <input className="input" value={p.name} onChange={e => patch(p.id, { name: e.target.value })} />
                </label>
                <label>API 地址（OpenAI 兼容，含到最后一级路径）
                  <input className="input" value={p.base_url} onChange={e => patch(p.id, { base_url: e.target.value.trim() })} placeholder="https://..." />
                </label>
                <label>API Key（本地服务可留空）
                  <input className="input" type="password" value={p.api_key} onChange={e => patch(p.id, { api_key: e.target.value })} placeholder="sk-..." />
                </label>
                <label>模型名
                  <input className="input" value={p.model} onChange={e => patch(p.id, { model: e.target.value })} placeholder="glm-4.5-air / deepseek-chat / ..." />
                </label>
              </div>
              <div className="provider-actions">
                <button className="btn btn-ghost btn-sm" onClick={() => test(p)} disabled={testingId !== null}>
                  {testingId === p.id && <Loader2 size={13} className="spin-once" />}
                  {testingId === p.id ? '测试中…' : '测试连接'}
                </button>
                <button className="btn btn-ghost btn-sm btn-danger" onClick={() => remove(p.id)}>
                  <Trash2 size={13} /> 删除
                </button>
              </div>
              {testOut[p.id] && (
                <p className={`test-out ${testOut[p.id].ok ? 'test-ok' : 'test-err'}`}>{testOut[p.id].msg}</p>
              )}
            </div>
          ))}

          <div className="provider-card">
            <div className="provider-grid">
              <label>搜索引擎（岗位雷达 / 公司背调 直连模式）
                <select className="input" value={search.engine} onChange={e => patchSearch({ engine: e.target.value as SearchConfig['engine'] })}>
                  {SEARCH_ENGINES.map(e => (
                    <option key={e.id} value={e.id}>{e.label} · {e.quota}</option>
                  ))}
                </select>
              </label>
              <label>搜索 API Key
                <input
                  className="input"
                  type="password"
                  value={search.api_key}
                  onChange={e => patchSearch({ api_key: e.target.value })}
                  placeholder={search.engine === 'zhipu' ? '与智谱模型 Key 相同' : search.engine === 'serper' ? 'Serper API Key' : search.engine === 'brave' ? 'Brave Subscription Token' : search.engine === 'bocha' ? 'sk-...（博查 Key）' : 'tvly-...'}
                  disabled={search.engine === 'none' || !SEARCH_ENGINES.find(e => e.id === search.engine)?.needKey}
                />
              </label>
              {search.engine === 'searxng' && (
                <label>自建 SearXNG 地址（需在 settings.yml 打开 json 格式）
                  <input className="input" value={search.searxng_url} onChange={e => patchSearch({ searxng_url: e.target.value })} placeholder="http://127.0.0.1:8888" />
                </label>
              )}
              {search.engine === 'mcp' && (
                <>
                  <label>MCP 服务器 id（在「扩展中心」配置）
                    <input className="input" value={search.mcp_server_id} onChange={e => patchSearch({ mcp_server_id: e.target.value })} placeholder="如 searxng / jobspy" />
                  </label>
                  <label>检索工具名
                    <input className="input" value={search.mcp_tool} onChange={e => patchSearch({ mcp_tool: e.target.value })} placeholder="如 search / web_search / fetch_url" />
                  </label>
                  <label>查询参数名
                    <input className="input" value={search.mcp_query_arg} onChange={e => patchSearch({ mcp_query_arg: e.target.value })} placeholder="query / q / keyword" />
                  </label>
                </>
              )}
              <label>备用引擎（主引擎无结果/报错时自动切换）
                <select className="input" value={search.fallback_engine} onChange={e => patchSearch({ fallback_engine: e.target.value as SearchConfig['engine'] })}>
                  {SEARCH_ENGINES.map(e => (
                    <option key={e.id} value={e.id}>{e.id === 'none' ? '不启用' : e.label}</option>
                  ))}
                </select>
              </label>
              <label>备用引擎 API Key
                <input
                  className="input"
                  type="password"
                  value={search.fallback_api_key}
                  onChange={e => patchSearch({ fallback_api_key: e.target.value })}
                  placeholder={search.fallback_engine === 'tavily' ? 'tvly-...' : '备用 Key'}
                  disabled={search.fallback_engine === 'none'}
                />
              </label>
              <label>时间范围
                <select className="input" value={search.days} onChange={e => patchSearch({ days: Number(e.target.value) })}>
                  <option value={0}>不限</option>
                  <option value={1}>近 24 小时</option>
                  <option value={7}>近 7 天</option>
                  <option value={30}>近 30 天</option>
                </select>
              </label>
              <label>每路结果数（3–20，越大召回越多）
                <input className="input" type="number" min={3} max={20} value={search.max_results} onChange={e => patchSearch({ max_results: Number(e.target.value) })} />
              </label>
              <label>限定域名（逗号分隔，可空）
                <input className="input" value={search.include_domains} onChange={e => patchSearch({ include_domains: e.target.value })} placeholder="zhaopin.com, 51job.com" />
              </label>
              <label>排除域名（逗号分隔，可空）
                <input className="input" value={search.exclude_domains} onChange={e => patchSearch({ exclude_domains: e.target.value })} placeholder="58.com, liepin.com" />
              </label>
              <label>排除关键词（查询负词，逗号分隔）
                <input className="input" value={search.exclude_keywords} onChange={e => patchSearch({ exclude_keywords: e.target.value })} placeholder="外包, 派遣, 中介" />
              </label>
              <label>正文抓取器
                <select className="input" value={search.fetcher} onChange={e => patchSearch({ fetcher: e.target.value as SearchConfig['fetcher'] })}>
                  <option value="auto">自动（装了 crawl4ai 就用，否则轻量抓取）</option>
                  <option value="http">轻量抓取（httpx + trafilatura）</option>
                  <option value="crawl4ai">crawl4ai（需另行安装，支持 JS 渲染）</option>
                </select>
              </label>
              <label>单次最多抓取页数（0–16）
                <input className="input" type="number" min={0} max={16} value={search.fetch_limit} onChange={e => patchSearch({ fetch_limit: Number(e.target.value) })} />
              </label>
            </div>
            <div className="provider-actions">
              <label className="check">
                <input type="checkbox" checked={search.fetch_pages} onChange={e => patchSearch({ fetch_pages: e.target.checked })} />
                抓取公开页正文（补全 JD 全文）
              </label>
              <label className="check">
                <input type="checkbox" checked={search.skip_login_walls} onChange={e => patchSearch({ skip_login_walls: e.target.checked })} />
                跳过登录墙平台（BOSS直聘 / 领英等，仅保留摘要与直达链接）
              </label>
              <button
                className="btn btn-ghost btn-sm"
                disabled={searchTesting || search.engine === 'none'}
                onClick={async () => {
                  setSearchTesting(true);
                  setSearchTest(null);
                  try {
                    const r = await testSearch(search.engine, search.api_key);
                    if (!r.ok) {
                      setSearchTest({ ok: false, msg: r.error });
                    } else if (r.ok && 'count' in r && r.count !== undefined) {
                      setSearchTest({
                        ok: r.count > 0,
                        msg: r.count > 0
                          ? `检索可用：${r.engine} 返回 ${r.count} 条（${r.latency_ms}ms）示例「${r.samples?.[0]?.title || ''}」`
                          : `引擎可用但返回 0 条：${r.note || '换个关键词再试'}`,
                      });
                    }
                  } finally {
                    setSearchTesting(false);
                  }
                }}
              >
                {searchTesting ? <Loader2 size={13} className="spin-once" /> : null}
                测试检索（额度/Key 自检）
              </button>
            </div>
            {searchTest && (
              <p className={`test-out ${searchTest.ok ? 'test-ok' : 'test-err'}`}>{searchTest.msg}</p>
            )}
            <p className="dialog-hint">
              不配搜索时，雷达 / 背调仍可运行，但只能基于模型既有知识输出方向性内容，报告中会明确标注。
              Tavily 支持原生域名限定与时间范围；智谱搜索用 site: 与「最新」做降级近似。抓取仅针对公开页面，不登录、不绕过风控。
              <br />
              <b>额度用尽怎么办</b>：Tavily 免费额度每月 1000 次，用尽会报 432（此时可等重置、升级套餐，或切到 Serper / Brave / 博查）；
              智谱余额不足会报 429（充值或换引擎）。点上方「测试检索」一秒就能确认到底是额度、Key 还是网络问题。
              <br />
              <b>检索结果缓存 24 小时</b>：同一查询重复运行不再消耗额度（缓存目录 <code>data/cache/search</code>，可随时删）。
              <br />
              <b>「排除关键词」不再拼进查询</b>：以前的 <code>-校招 -中介…</code> 会让引擎直接零召回，现在只作为模型筛选指令使用。
            </p>
          </div>
        </>
      )}
    </div>
  );
}
