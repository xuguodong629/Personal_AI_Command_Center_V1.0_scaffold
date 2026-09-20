import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchProviders, type ModelProvider } from './backend';

/**
 * 共享的模型供应商列表：挂载时拉取，设置弹窗每次关闭后刷新。
 * 所有模块共用同一个默认模型选择（存 localStorage 'jc-provider'）。
 * online：本地后端（:8787）是否在线 —— null=读取中 / true=在线 / false=离线。
 */
export function useProviders(settingsOpen: boolean) {
  const [providers, setProviders] = useState<ModelProvider[] | null>(null);
  const [providerId, setProviderId] = useState(() => localStorage.getItem('jc-provider') || '');
  const [online, setOnline] = useState<boolean | null>(null);

  const refresh = useCallback(() => {
    fetchProviders().then(r => {
      setOnline(r.ok);
      const list = r.ok && r.providers ? r.providers : [];
      setProviders(list);
      setProviderId(cur => (list.some(p => p.id === cur) ? cur : list[0]?.id ?? ''));
    });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const sawOpen = useRef(false);
  useEffect(() => {
    if (settingsOpen) {
      sawOpen.current = true;
      return;
    }
    if (sawOpen.current) {
      sawOpen.current = false;
      refresh();
    }
  }, [settingsOpen, refresh]);

  const select = useCallback((id: string) => {
    setProviderId(id);
    localStorage.setItem('jc-provider', id);
  }, []);

  return { providers, providerId, select, online };
}
