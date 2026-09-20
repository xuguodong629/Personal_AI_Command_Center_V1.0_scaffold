import { useCallback, useEffect, useState } from 'react';
import { Blocks, Bot, FileText, Mic, Moon, Search, Settings as SettingsIcon, ShieldCheck, Sun, TrendingUp } from 'lucide-react';
import CommandPalette, { type PaletteAction } from '../components/CommandPalette';
import SettingsModal from '../components/SettingsModal';
import Sidebar from '../components/Sidebar';
import Toasts, { type ToastItem } from '../components/Toasts';
import BackgroundView from '../views/BackgroundView';
import ChatView from '../views/ChatView';
import IndustryView from '../views/IndustryView';
import InterviewView from '../views/InterviewView';
import ExtensionsView from '../views/ExtensionsView';
import RadarView from '../views/RadarView';
import ResumeView from '../views/ResumeView';
import { loadConfig, saveConfig, type DifyConfig } from '../lib/dify';
import { useProviders } from '../lib/useProviders';
import type { NavItem, ViewId } from '../lib/views';

const THEME_KEY = 'jc-theme';
const VIEW_IDS: ViewId[] = ['radar', 'industry', 'bg', 'resume', 'chat', 'interview', 'ext'];
const SHORTCUT_DIGITS = ['1', '2', '3', '4', '5', '6', '7'];

type Theme = 'dark' | 'light';

function initialView(): ViewId {
  const h = window.location.hash.replace('#', '');
  return (VIEW_IDS as string[]).includes(h) ? (h as ViewId) : 'radar';
}

function initialTheme(): Theme {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === 'dark' || saved === 'light') return saved;
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export default function JobCenter() {
  const [view, setView] = useState<ViewId>(initialView);
  const [cfg, setCfg] = useState<DifyConfig>(loadConfig);
  const [cfgOpen, setCfgOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [radarResult, setRadarResult] = useState('');

  // V0.3：直连模型与后端状态（左下角状态卡；Dify 已非必需）
  const { providers, online } = useProviders(cfgOpen);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    window.location.hash = view;
  }, [view]);

  const pushToast = useCallback((kind: ToastItem['kind'], msg: string) => {
    const id = Math.random().toString(36).slice(2);
    setToasts(ts => [...ts, { id, kind, msg }]);
    setTimeout(() => setToasts(ts => ts.filter(t => t.id !== id)), 3200);
  }, []);

  const saveCfg = useCallback((next: DifyConfig) => {
    setCfg(next);
    saveConfig(next);
  }, []);

  const toggleTheme = useCallback(() => setTheme(t => (t === 'dark' ? 'light' : 'dark')), []);

  // 全局快捷键：Ctrl/Cmd+K 命令面板，Ctrl+1/2/3 切换视图，Ctrl+, 设置
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (!mod) return;
      const k = e.key.toLowerCase();
      if (k === 'k') {
        e.preventDefault();
        setPaletteOpen(v => !v);
      } else if (SHORTCUT_DIGITS.includes(e.key)) {
        e.preventDefault();
        setView(VIEW_IDS[Number(e.key) - 1]);
      } else if (e.key === ',') {
        e.preventDefault();
        setCfgOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const nav: NavItem[] = [
    { id: 'radar', label: '岗位雷达', desc: '机会池 · 信号增强', icon: Search, shortcut: 'Ctrl 1' },
    { id: 'industry', label: '行业赛道', desc: '五档研判 · 进入时机', icon: TrendingUp, shortcut: 'Ctrl 2' },
    { id: 'bg', label: '公司背调', desc: '风控体检 · 尽调 16 章', icon: ShieldCheck, shortcut: 'Ctrl 3' },
    { id: 'resume', label: '定制简历', desc: 'JD 解析 · 六维匹配', icon: FileText, shortcut: 'Ctrl 4' },
    { id: 'chat', label: 'AI 助手', desc: '直连模型 · 即问即答', icon: Bot, shortcut: 'Ctrl 5' },
    { id: 'interview', label: '模拟面试', desc: '多轮问答 · 复盘报告', icon: Mic, shortcut: 'Ctrl 6' },
    { id: 'ext', label: '扩展中心', desc: 'MCP 服务器 · 技能', icon: Blocks, shortcut: 'Ctrl 7' },
  ];

  // V0.3：AI 状态 = 本地后端在线 + 已配置直连模型；未启动后端或未添加模型时给出引导
  const aiStatus =
    online === null ? { label: '连接后端中…', level: 'warn' as const }
    : !online ? { label: '后端未启动 :8787', level: 'off' as const }
    : providers && providers.length > 0 ? { label: '模型已就绪', level: 'ok' as const }
    : { label: '未添加模型（去设置）', level: 'warn' as const };

  const actions: PaletteAction[] = [
    ...nav.map(item => ({
      id: `go-${item.id}`,
      label: `前往：${item.label}`,
      hint: item.shortcut,
      icon: item.icon,
      run: () => setView(item.id),
    })),
    { id: 'settings', label: '打开设置（模型直连）', hint: 'Ctrl ,', icon: SettingsIcon, run: () => setCfgOpen(true) },
    {
      id: 'theme',
      label: theme === 'dark' ? '切换到浅色主题' : '切换到深色主题',
      icon: theme === 'dark' ? Sun : Moon,
      run: toggleTheme,
    },
  ];

  const openSettings = useCallback(() => setCfgOpen(true), []);
  const goTo = useCallback((v: ViewId) => setView(v), []);

  return (
    <div className="app">
      <Sidebar
        nav={nav}
        view={view}
        onSelect={goTo}
        theme={theme}
        onToggleTheme={toggleTheme}
        onOpenSettings={openSettings}
        onOpenPalette={() => setPaletteOpen(true)}
        aiStatus={aiStatus}
      />

      <main className="main" key={view}>
        {view === 'radar' && (
          <RadarView
            cfg={cfg}
            settingsOpen={cfgOpen}
            radarResult={radarResult}
            setRadarResult={setRadarResult}
            goTo={goTo}
            openSettings={openSettings}
            pushToast={pushToast}
          />
        )}
        {view === 'industry' && (
          <IndustryView settingsOpen={cfgOpen} openSettings={openSettings} pushToast={pushToast} />
        )}
        {view === 'bg' && <BackgroundView cfg={cfg} settingsOpen={cfgOpen} openSettings={openSettings} pushToast={pushToast} />}
        {view === 'resume' && <ResumeView cfg={cfg} settingsOpen={cfgOpen} openSettings={openSettings} pushToast={pushToast} />}
        {view === 'chat' && <ChatView settingsOpen={cfgOpen} openSettings={openSettings} pushToast={pushToast} />}
        {view === 'interview' && <InterviewView settingsOpen={cfgOpen} openSettings={openSettings} pushToast={pushToast} />}
        {view === 'ext' && <ExtensionsView settingsOpen={cfgOpen} openSettings={openSettings} pushToast={pushToast} />}
      </main>

      <SettingsModal open={cfgOpen} cfg={cfg} onSave={saveCfg} onClose={() => setCfgOpen(false)} />
      <CommandPalette open={paletteOpen} actions={actions} onClose={() => setPaletteOpen(false)} />
      <Toasts items={toasts} />
    </div>
  );
}
