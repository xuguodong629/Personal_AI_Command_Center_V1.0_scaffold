import type { ComponentType } from 'react';

export type ViewId = 'radar' | 'industry' | 'bg' | 'resume' | 'chat' | 'interview' | 'ext';

export interface NavItem {
  id: ViewId;
  label: string;
  desc: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  /** 对应工作流的 API Key 是否已配置；undefined 表示不显示状态点 */
  ready?: boolean;
  shortcut: string;
}
