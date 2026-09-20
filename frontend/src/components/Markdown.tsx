import type { MouseEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { openExternal } from '../lib/backend';

// 工作流输出的报告多为 Markdown 文本，统一在此渲染。
// 注意：桌面端（Tauri）里若让 <a> 直接跳转，会把应用窗口导航到外部网站，
// 关闭该窗口/返回后表现为"整个程序退出"；因此这里拦截外链，交给系统浏览器打开。
export default function Markdown({ text }: { text: string }) {
  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement | null;
    const anchor = target?.closest?.('a');
    if (!anchor) return;
    const href = anchor.getAttribute('href') || '';
    if (!/^https?:\/\//i.test(href)) return; // 站内锚点 / 相对链接照常
    e.preventDefault();
    e.stopPropagation();
    openExternal(href).then(r => {
      // 兜底：后端不可用时退回新标签页（浏览器模式可用）
      if (!r.ok) window.open(href, '_blank', 'noopener');
    });
  };

  return (
    <div className="md" onClick={onClick}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}
