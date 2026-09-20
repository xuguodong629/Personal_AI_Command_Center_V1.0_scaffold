import { Command, Moon, Radar, Settings, Sun } from 'lucide-react';
import type { NavItem } from '../lib/views';
import type { ViewId } from '../lib/views';

interface Props {
  nav: NavItem[];
  view: ViewId;
  onSelect: (v: ViewId) => void;
  theme: 'dark' | 'light';
  onToggleTheme: () => void;
  onOpenSettings: () => void;
  onOpenPalette: () => void;
  /** AI 运行状态：本地后端 + 直连模型配置（V0.3 起默认直连，不依赖 Dify） */
  aiStatus: { label: string; level: 'ok' | 'warn' | 'off' };
}

export default function Sidebar({ nav, view, onSelect, theme, onToggleTheme, onOpenSettings, onOpenPalette, aiStatus }: Props) {
  return (
    <aside className="side">
      <div className="brand">
        <div className="brand-tile">
          <Radar size={19} />
        </div>
        <div className="brand-text">
          <b>AI 猎头中枢</b>
          <span>PERSONAL AI COMMAND CENTER</span>
        </div>
      </div>

      <div className="side-section">模块</div>
      <nav className="nav">
        {nav.map((item, i) => {
          const Icon = item.icon;
          const active = view === item.id;
          return (
            <button
              key={item.id}
              className={`navitem${active ? ' active' : ''}`}
              onClick={() => onSelect(item.id)}
              title={item.ready === false ? `${item.label}（未配置）` : item.label}
            >
              <Icon size={17} />
              <span className="nav-text">
                <b>{item.label}</b>
                <small>{item.desc}</small>
              </span>
              {item.ready !== undefined && (
                <span className={`nav-end${item.ready ? ' ok' : ''}`} title={item.ready ? '已配置' : '未配置'} />
              )}
              <span className="kbd nav-kbd">{i + 1}</span>
            </button>
          );
        })}
      </nav>

      <div className="side-foot">
        <div className={`statuscard status-${aiStatus.level}`}>
          <span className="statusdot" />
          <span className="status-text">{aiStatus.label}</span>
        </div>
        <div className="side-actions">
          <button className="iconbtn" onClick={onOpenPalette} title="命令面板（Ctrl K）">
            <Command size={16} />
          </button>
          <button className="iconbtn" onClick={onToggleTheme} title={theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'}>
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button className="iconbtn" onClick={onOpenSettings} title="设置（Ctrl ,）">
            <Settings size={16} />
          </button>
        </div>
        <div className="side-ver">V0.3 · 本地运行 · 数据不出本机</div>
      </div>
    </aside>
  );
}
