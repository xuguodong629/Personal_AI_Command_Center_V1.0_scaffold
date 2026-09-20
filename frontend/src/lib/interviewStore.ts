// 面试工作区：每场面试独立存档（本地 data/interview/*.json），支持列表、检索、标签、新建、删除

const BASE = localStorage.getItem('jc-backend-url') || 'http://127.0.0.1:8787';

export interface SessionMessage {
  role: string;
  content: string;
}

export interface SessionSummary {
  id: string;
  title: string;
  company: string;
  persona: string;
  finished: boolean;
  progress: string;
  tags: string[];
  created_at: number;
  updated_at: number;
  message_count: number;
  has_review: boolean;
}

export interface SessionDetail extends SessionSummary {
  jd: string;
  stage: string;
  round_no: number;
  messages: SessionMessage[];
  review: string;
}

export type SessionPayload = Partial<Omit<SessionDetail, 'id' | 'created_at' | 'updated_at' | 'message_count'>>;

async function call<T>(path: string, init?: RequestInit): Promise<{ ok: true } & T | { ok: false; error: string }> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
    const data = (await res.json().catch(() => null)) as Record<string, unknown> | null;
    if (!res.ok) {
      const detail = (data?.detail as string) || `HTTP ${res.status}`;
      return { ok: false, error: detail };
    }
    return data as { ok: true } & T;
  } catch {
    return { ok: false, error: '无法连接本地后端（127.0.0.1:8787）' };
  }
}

export function listSessions(q = '', tag = '') {
  const qs = new URLSearchParams();
  if (q) qs.set('q', q);
  if (tag) qs.set('tag', tag);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return call<{ sessions: SessionSummary[] }>(`/api/interview/sessions${suffix}`);
}

export function listTags() {
  return call<{ tags: Array<{ tag: string; count: number }> }>('/api/interview/tags');
}

export function createSession(payload: SessionPayload) {
  return call<{ session: SessionDetail }>('/api/interview/sessions', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getSession(id: string) {
  return call<{ session: SessionDetail }>(`/api/interview/sessions/${id}`);
}

export function updateSession(id: string, payload: SessionPayload) {
  return call<{ session: SessionDetail }>(`/api/interview/sessions/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function deleteSession(id: string) {
  return call<Record<string, never>>(`/api/interview/sessions/${id}`, { method: 'DELETE' });
}

export function autoTagSession(id: string, providerId: string) {
  return call<{ tags: string[] }>(`/api/interview/sessions/${id}/auto-tag`, {
    method: 'POST',
    body: JSON.stringify({ provider_id: providerId }),
  });
}

export const PERSONA_LABELS: Record<string, string> = {
  hr: 'HR 初面',
  region_director: '直属大区总',
  boss: '老板终面',
  stress: '压力面',
};
