import { useEffect, useRef, useState } from 'react';
import { Mic, MicOff, RefreshCw, Send, Sparkles, Square, VolumeX } from 'lucide-react';
import ResultPanel from '../components/ResultPanel';
import { interviewTurn, interviewReview, type ChatMsg } from '../lib/backend';
import { useProviders } from '../lib/useProviders';
import { loadLocalDefaults, buildCandidatePrompt } from '../lib/profile';
import {
  PERSONA_LABELS,
  autoTagSession,
  createSession,
  deleteSession,
  getSession,
  listSessions,
  listTags,
  updateSession,
  type SessionSummary,
} from '../lib/interviewStore';
import {
  ContinuousListener,
  RATE_OPTIONS,
  Recorder,
  SpeechQueue,
  VOICE_OPTIONS,
  WHISPER_MODEL_OPTIONS,
  fetchVoiceStatus,
  proofreadText,
  saveVoiceConfig,
  synthesize,
  transcribe,
  type VoiceConfig,
} from '../lib/voice';

const STORE_KEY = 'jc-interview';

interface Msg {
  role: 'assistant' | 'user';
  content: string;
}

interface Saved {
  persona: string;
  company: string;
  jd: string;
  messages: Msg[];
  stage: string;
  roundNo: number;
  progress: string;
  finished: boolean;
  voiceOn: boolean;
  autoSubmit: boolean;
  proofread?: boolean;
  continuous?: boolean;
  bargeIn?: boolean;
  silenceMs?: number;
  sensitivity?: number;
  showInterim?: boolean;
  sessionId?: string;
  title?: string;
  tags?: string[];
  sideCollapsed?: boolean;
  configCollapsed?: boolean;
}

const PERSONAS = [
  { key: 'hr', label: 'HR 初面' },
  { key: 'region_director', label: '直属大区总' },
  { key: 'boss', label: '老板终面' },
  { key: 'stress', label: '压力面' },
];

function loadSaved(): Partial<Saved> {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) return JSON.parse(raw) as Partial<Saved>;
  } catch { /* ignore */ }
  return {};
}

interface Props {
  settingsOpen: boolean;
  openSettings: () => void;
  pushToast: (kind: 'ok' | 'err' | 'info', msg: string) => void;
}

/** 模拟面试（P1 文字 + P2 语音对话）：面试官语音提问，你语音回答，结束后出复盘报告 */
export default function InterviewView({ settingsOpen, openSettings, pushToast }: Props) {
  const saved = useRef(loadSaved()).current;
  const { providerId } = useProviders(settingsOpen);

  const [persona, setPersona] = useState(saved.persona || 'region_director');
  const [company, setCompany] = useState(saved.company || '');
  const [jd, setJd] = useState(saved.jd || '');
  const [messages, setMessages] = useState<Msg[]>(saved.messages || []);
  const [stage, setStage] = useState(saved.stage || 'intro');
  const [roundNo, setRoundNo] = useState(saved.roundNo || 1);
  const [progress, setProgress] = useState(saved.progress || '');
  const [finished, setFinished] = useState(Boolean(saved.finished));
  const [voiceOn, setVoiceOn] = useState(saved.voiceOn !== false);
  const [autoSubmit, setAutoSubmit] = useState(Boolean(saved.autoSubmit));
  const [proofread, setProofread] = useState(saved.proofread !== false);
  // 连续对话（免提）：VAD 自动断句 + 播报后自动继续听 + 可打断
  const [continuous, setContinuous] = useState(Boolean(saved.continuous));
  const [bargeIn, setBargeIn] = useState(saved.bargeIn !== false);
  const [silenceMs, setSilenceMs] = useState(saved.silenceMs ?? 800);
  const [sensitivity, setSensitivity] = useState(saved.sensitivity ?? 1.2);
  const [level, setLevel] = useState(0);
  const [micHot, setMicHot] = useState(false);
  // 边说边显示识别文字
  const [showInterim, setShowInterim] = useState(saved.showInterim !== false);
  const [interimText, setInterimText] = useState('');
  // 工作区（面试存档）
  const [sessionId, setSessionId] = useState(saved.sessionId || '');
  const [title, setTitle] = useState(saved.title || '');
  const [tags, setTags] = useState<string[]>(saved.tags || []);
  const [tagDraft, setTagDraft] = useState((saved.tags || []).join('、'));
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [tagList, setTagList] = useState<Array<{ tag: string; count: number }>>([]);
  const [search, setSearch] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [savedHint, setSavedHint] = useState('');
  // 折叠/展开 + 列表内重命名
  const [sideCollapsed, setSideCollapsed] = useState(Boolean(saved.sideCollapsed));
  const [configCollapsed, setConfigCollapsed] = useState(Boolean(saved.configCollapsed));
  const [renamingId, setRenamingId] = useState('');
  const [renameDraft, setRenameDraft] = useState('');
  const [voiceCfg, setVoiceCfg] = useState<VoiceConfig>({
    tts_voice: 'zh-CN-YunxiNeural',
    tts_rate: '+20%',
    whisper_model: 'small',
    whisper_device: 'cpu',
    whisper_compute: 'int8',
  });
  const [voiceHint, setVoiceHint] = useState('');
  const [recState, setRecState] = useState<'idle' | 'recording' | 'transcribing'>('idle');
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [err, setErr] = useState('');
  const [profile, setProfile] = useState('');
  const [review, setReview] = useState('');
  const [reviewBusy, setReviewBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const recorderRef = useRef<Recorder | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const queueRef = useRef<SpeechQueue | null>(null);
  const listenerRef = useRef<ContinuousListener | null>(null);
  const busyRef = useRef(false);
  const finishedRef = useRef(false);
  const interimBusyRef = useRef(false);
  const answerRef = useRef('');
  const lastInterimRef = useRef('');
  const saveTimerRef = useRef<number | null>(null);
  const sessionIdRef = useRef('');

  useEffect(() => {
    busyRef.current = busy;
    finishedRef.current = finished;
  }, [busy, finished]);

  useEffect(() => {
    answerRef.current = answer;
  }, [answer]);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  /** 分句流式播报队列（懒创建；播放状态回写 speaking + 通知监听器用于防回声） */
  const getQueue = (): SpeechQueue => {
    if (!queueRef.current) {
      queueRef.current = new SpeechQueue({
        onState: sp => {
          setSpeaking(sp);
          if (listenerRef.current) listenerRef.current.playing = sp;
        },
      });
    }
    queueRef.current.setVoice(voiceCfg.tts_voice, voiceCfg.tts_rate);
    return queueRef.current;
  };

  useEffect(() => {
    loadLocalDefaults().then(d => setProfile(buildCandidatePrompt(d)));
    fetchVoiceStatus().then(s => {
      if (!s) {
        setVoiceHint('语音服务未启动（后端 8787 未响应）');
        return;
      }
      if (s.config) setVoiceCfg(s.config);
      const stt = s.stt?.available;
      const tts = s.tts?.available;
      setVoiceHint(
        stt && tts
          ? `语音就绪：识别 ${s.stt.model}（本地）/ 播报 ${s.tts.voice} ${s.tts.rate || ''}`
          : `${stt ? '' : '识别不可用（需装 faster-whisper）；'}${tts ? '' : '播报不可用（需装 edge-tts，将用系统语音）'}`,
      );
    });
    return () => {
      recorderRef.current?.cancel();
      listenerRef.current?.stop();
      queueRef.current?.stop();
      window.speechSynthesis?.cancel();
    };
  }, []);

  useEffect(() => {
    const data: Saved = {
      persona, company, jd, messages, stage, roundNo, progress, finished,
      voiceOn, autoSubmit, proofread, continuous, bargeIn, silenceMs, sensitivity,
      showInterim, sessionId, title, tags, sideCollapsed, configCollapsed,
    };
    localStorage.setItem(STORE_KEY, JSON.stringify(data));
    // 内容变化 → 防抖自动存档到工作区
    if (sessionIdRef.current) {
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = window.setTimeout(() => {
        void persist(sessionIdRef.current);
      }, 1200);
    }
  }, [persona, company, jd, messages, stage, roundNo, progress, finished, voiceOn, autoSubmit, proofread, continuous, bargeIn, silenceMs, sensitivity, showInterim, sessionId, title, tags, sideCollapsed, configCollapsed]);

  /** 确保存在工作区（没有就懒创建一个），返回 session id */
  const ensureSession = async (): Promise<string> => {
    if (sessionId) return sessionId;
    const created = await createSession({ persona, title: '', company, tags });
    if (!created.ok) {
      pushToast('err', `新建工作区失败：${created.error}`);
      return '';
    }
    setSessionId(created.session.id);
    setTitle(created.session.title);
    void refreshList();
    return created.session.id;
  };

  /** 存档当前面试到工作区 */
  const persist = async (sid: string) => {
    const id = sid || (await ensureSession());
    if (!id) return;
    const r = await updateSession(id, {
      title: title || undefined,
      company,
      persona,
      jd,
      stage,
      round_no: roundNo,
      progress,
      finished,
      tags,
      messages: messages.map(m => ({ role: m.role, content: m.content })),
      review,
    });
    if (r.ok) {
      setSavedHint(`已保存 ${new Date().toLocaleTimeString()}`);
      void refreshList();
    } else {
      setSavedHint(`保存失败：${r.error}`);
    }
  };

  const refreshList = async () => {
    const r = await listSessions(search, tagFilter);
    if (r.ok) setSessions(r.sessions);
    const t = await listTags();
    if (t.ok) setTagList(t.tags);
  };

  useEffect(() => {
    void refreshList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, tagFilter]);

  /** 新建面试工作区（清空重开） */
  const newSession = async () => {
    stopSpeak();
    stopListening();
    setMessages([]);
    setReview('');
    setStage('intro');
    setRoundNo(1);
    setProgress('');
    setFinished(false);
    setAnswer('');
    setInterimText('');
    setErr('');
    setCompany('');
    setJd('');
    setTags([]);
    setTagDraft('');
    const r = await createSession({ persona, title: '', company: '', tags: [] });
    if (r.ok) {
      setSessionId(r.session.id);
      setTitle(r.session.title);
      pushToast('ok', '已新建面试工作区');
      void refreshList();
    } else {
      setSessionId('');
      pushToast('err', `新建失败：${r.error}`);
    }
  };

  /** 载入历史面试 */
  const loadSessionById = async (id: string) => {
    stopSpeak();
    stopListening();
    const r = await getSession(id);
    if (!r.ok) {
      pushToast('err', `载入失败：${r.error}`);
      return;
    }
    const s = r.session;
    setSessionId(s.id);
    setTitle(s.title || '');
    setCompany(s.company || '');
    setPersona(s.persona || 'region_director');
    setJd(s.jd || '');
    setTags(s.tags || []);
    setTagDraft((s.tags || []).join('、'));
    setMessages((s.messages || []) as Msg[]);
    setStage(s.stage || 'intro');
    setRoundNo(s.round_no || 1);
    setProgress(s.progress || '');
    setFinished(Boolean(s.finished));
    setReview(s.review || '');
    setAnswer('');
    setInterimText('');
    setErr('');
    pushToast('ok', `已载入：${s.title || '未命名面试'}`);
  };

  const removeSessionById = async (id: string) => {
    if (!window.confirm('删除这条面试记录？该操作不可恢复。')) return;
    const r = await deleteSession(id);
    if (!r.ok) {
      pushToast('err', `删除失败：${r.error}`);
      return;
    }
    if (id === sessionId) {
      setSessionId('');
      setMessages([]);
      setReview('');
      setTitle('');
    }
    pushToast('ok', '已删除');
    void refreshList();
  };

  const commitTags = () => {
    const list = tagDraft.split(/[，,、;；\s]+/).filter(Boolean).slice(0, 8);
    setTags(list);
    setTagDraft(list.join('、'));
  };

  /** 重命名某条面试记录（列表内联编辑） */
  const startRename = (id: string, currentTitle: string) => {
    setRenamingId(id);
    setRenameDraft(currentTitle || '');
  };

  const commitRename = async (id: string) => {
    const next = renameDraft.trim();
    setRenamingId('');
    if (!next) return;
    const r = await updateSession(id, { title: next });
    if (!r.ok) {
      pushToast('err', `重命名失败：${r.error}`);
      return;
    }
    if (id === sessionId) setTitle(next);
    pushToast('ok', '已重命名');
    void refreshList();
  };

  const suggestTags = async () => {
    if (!providerId) {
      openSettings();
      pushToast('err', '请先选择模型');
      return;
    }
    const id = sessionId || (await ensureSession());
    if (!id) return;
    const r = await autoTagSession(id, providerId);
    if (!r.ok) {
      pushToast('err', `标签生成失败：${r.error}`);
      return;
    }
    setTags(r.tags);
    setTagDraft(r.tags.join('、'));
    pushToast('ok', '已生成分类标签');
  };

  /** 修改语音配置：本地更新 + 持久化到后端（换识别模型会触发重载/下载） */
  const applyVoiceCfg = async (patch: Partial<VoiceConfig>) => {
    const next = { ...voiceCfg, ...patch };
    setVoiceCfg(next);
    const ok = await saveVoiceConfig(next);
    pushToast(ok ? 'ok' : 'err', ok ? '语音设置已保存' : '语音设置保存失败（后端未响应）');
  };

  /** 试听：用当前音色与语速合成一句 */
  const preview = async () => {
    const url = await synthesize('你好，我是面试官，请先做个自我介绍。', voiceCfg.tts_voice, voiceCfg.tts_rate);
    if (!url) {
      pushToast('err', '试听失败（语音服务不可用）');
      return;
    }
    stopSpeak();
    const audio = new Audio(url);
    audioRef.current = audio;
    audio.onended = () => URL.revokeObjectURL(url);
    await audio.play().catch(() => pushToast('err', '播放被拒绝，请再点一次'));
  };

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, busy]);

  /** 播报面试官内容：分句流式（首句先出声） */
  const speak = async (text: string) => {
    if (!voiceOn) return;
    getQueue().push(text);
  };

  const stopSpeak = () => {
    queueRef.current?.stop();
    audioRef.current?.pause();
    audioRef.current = null;
    window.speechSynthesis?.cancel();
    setSpeaking(false);
  };

  /** 连续聆听：VAD 自动断句；播放中插话（barge-in）会打断面试官 */
  const startListening = async () => {
    if (listenerRef.current) return;
    const listener = new ContinuousListener({
      silenceMs,
      sensitivity,
      interimMs: showInterim ? 3000 : 0,
      onInterim: blob => {
        void handleInterim(blob);
      },
      onSpeechStart: () => {
        if (bargeIn && queueRef.current?.speaking) {
          queueRef.current.stop();
          pushToast('info', '已打断面试官');
        }
      },
      onUtterance: blob => {
        void handleUtterance(blob);
      },
      onLevel: (lvl, st) => {
        setLevel(Math.min(1, lvl * 14));
        setMicHot(st === 'speech');
      },
      onError: msg => setErr(msg),
    });
    listenerRef.current = listener;
    await listener.start();
    if (listener.listening) {
      setContinuous(true);
      pushToast('ok', '已开启连续对话（直接说话即可，停顿自动提交）');
    } else {
      listenerRef.current = null;
    }
  };

  const stopListening = () => {
    listenerRef.current?.stop();
    listenerRef.current = null;
    setMicHot(false);
    setLevel(0);
    setContinuous(false);
  };

  /** 边说边显示：用更快的小模型对"累计音频"做增量识别，实时写进输入框 */
  const handleInterim = async (blob: Blob) => {
    if (!showInterim || interimBusyRef.current) return;
    interimBusyRef.current = true;
    try {
      const r = await transcribe(blob, 'base');
      if (!r.ok || !r.text) return;
      const text = r.text.trim().replace(/^[，。！？、\s]+/, '');
      if (!text) return;
      setInterimText(text);
      // 未开启自动提交时，把识别内容实时写进输入框，方便复盘
      if (!autoSubmit && (answerRef.current === '' || answerRef.current === lastInterimRef.current)) {
        setAnswer(text);
        lastInterimRef.current = text;
      }
    } finally {
      interimBusyRef.current = false;
    }
  };

  /** 一段话说完 → 识别（+轻校对）→ 提交 */
  const handleUtterance = async (blob: Blob) => {
    if (busyRef.current || finishedRef.current) return; // 面试官思考中/已结束：丢弃，避免抢答
    if (recState === 'transcribing') return;
    setRecState('transcribing');
    try {
      const r = await transcribe(blob);
      if (!r.ok) {
        setErr(r.error || '语音识别失败');
        return;
      }
      let text = (r.text || '').trim();
      if (text && proofread && providerId) {
        text = (await proofreadText(providerId, text)).trim();
      }
      if (!text) return;
      await submit(text);
    } finally {
      setRecState('idle');
      setInterimText('');
      lastInterimRef.current = '';
    }
  };

  const call = async (history: Msg[], userAnswer: string, curStage: string, curRound: number) => {
    if (!providerId) {
      openSettings();
      pushToast('err', '请先在设置 → 模型直连中添加并选择模型');
      return null;
    }
    setBusy(true);
    setErr('');
    try {
      const r = await interviewTurn({
        provider_id: providerId,
        stage: curStage,
        round_no: curRound,
        history: history.map(m => ({ role: m.role, content: m.content })) as ChatMsg[],
        profile,
        jd,
        company,
        role_persona: persona,
        user_answer: userAnswer,
      });
      if (!r.ok) {
        setErr(r.error || '面试请求失败');
        return null;
      }
      return r;
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    stopSpeak();
    // 没有工作区就先建一个（每次面试独立存档）
    let sid = sessionId;
    if (!sid) {
      const created = await createSession({ persona, title: '', company, tags });
      if (created.ok) {
        sid = created.session.id;
        setSessionId(sid);
        setTitle(created.session.title);
        void refreshList();
      } else {
        pushToast('err', `新建工作区失败：${created.error}`);
        return;
      }
    }
    setMessages([]);
    setReview('');
    setStage('intro');
    setRoundNo(1);
    setProgress('');
    setFinished(false);
    setInterimText('');
    const r = await call([], '', 'intro', 1);
    if (!r) return;
    setMessages([{ role: 'assistant', content: r.reply }]);
    setStage(r.stage);
    setRoundNo(r.round_no);
    setProgress(r.progress);
    await speak(r.reply);
  };

  /** 提交回答；text 可覆盖（语音识别结果） */
  const submit = async (textOverride?: string) => {
    const text = (textOverride ?? answer).trim();
    if (!text) return;
    const withAnswer: Msg[] = [...messages, { role: 'user', content: text }];
    setMessages(withAnswer);
    setAnswer('');
    const r = await call(messages, text, stage, roundNo);
    if (!r) return;
    const next: Msg[] = [...withAnswer, { role: 'assistant', content: r.reply }];
    setMessages(next);
    setStage(r.stage);
    setRoundNo(r.round_no);
    setProgress(r.progress);
    await speak(r.reply);
    if (r.finished) {
      setFinished(true);
      stopListening();
      pushToast('ok', '面试结束，正在生成复盘报告…');
      await runReview(next);
    }
  };

  /** 麦克风：点击开始 / 再点结束并识别 */
  const toggleRecord = async () => {
    if (recState === 'recording') {
      setRecState('transcribing');
      const blob = await recorderRef.current?.stop();
      if (!blob || !blob.size) {
        setRecState('idle');
        setErr('没有录到声音，请重试');
        return;
      }
      const r = await transcribe(blob);
      if (!r.ok) {
        setRecState('idle');
        setErr(r.error || '语音识别失败');
        return;
      }
      let text = (r.text || '').trim();
      // 可选轻校对：只纠同音字/行业术语，不改语义
      if (text && proofread && providerId) {
        text = (await proofreadText(providerId, text)).trim();
      }
      setRecState('idle');
      if (!text) {
        setErr('未识别到内容，请再说一次');
        return;
      }
      if (autoSubmit) {
        await submit(text);
      } else {
        setAnswer(prev => (prev ? `${prev} ${text}` : text));
      }
      return;
    }
    try {
      const rec = new Recorder();
      await rec.start();
      recorderRef.current = rec;
      setErr('');
      setRecState('recording');
    } catch (e) {
      setRecState('idle');
      setErr(`无法访问麦克风：${(e as Error).message}（请检查系统麦克风权限）`);
    }
  };

  const runReview = async (history?: Msg[]) => {
    const h = history ?? messages;
    if (!h.length) {
      pushToast('err', '还没有面试内容');
      return;
    }
    if (!providerId) {
      openSettings();
      pushToast('err', '请先选择模型');
      return;
    }
    setReviewBusy(true);
    try {
      const r = await interviewReview({
        provider_id: providerId,
        history: h.map(m => ({ role: m.role, content: m.content })) as ChatMsg[],
        profile,
        jd,
        company,
        role_persona: persona,
      });
      if (!r.ok) {
        setErr(r.error || '复盘生成失败');
        return;
      }
      setReview(r.content);
      pushToast('ok', '复盘报告已生成');
    } finally {
      setReviewBusy(false);
    }
  };

  return (
    <div className="view">
      <header className="view-head">
        <h2>模拟面试</h2>
        <p>每场面试独立存档：语音提问 / 语音回答（含边说边显示）/ 复盘报告，可分类检索随时调取。</p>
      </header>

      <div className={`ws${sideCollapsed ? ' side-collapsed' : ''}`}>
        <aside className={`ws-side${sideCollapsed ? ' hidden' : ''}`}>
          <div className="ws-side-head">
            <input className="input" placeholder="搜索面试记录…" value={search} onChange={e => setSearch(e.target.value)} />
          </div>
          <div className="ws-tags">
            <button className={`tchip${tagFilter === '' ? ' on' : ''}`} onClick={() => setTagFilter('')}>全部 {sessions.length}</button>
            {tagList.map(t => (
              <button
                key={t.tag}
                className={`tchip${tagFilter === t.tag ? ' on' : ''}`}
                onClick={() => setTagFilter(tagFilter === t.tag ? '' : t.tag)}
              >
                {t.tag} {t.count}
              </button>
            ))}
          </div>
          <div className="ws-list">
            {sessions.map(s => (
              <div
                key={s.id}
                className={`ws-item${s.id === sessionId ? ' active' : ''}`}
                onClick={() => void loadSessionById(s.id)}
              >
                {renamingId === s.id ? (
                  <input
                    className="input ws-rename"
                    value={renameDraft}
                    autoFocus
                    onClick={e => e.stopPropagation()}
                    onChange={e => setRenameDraft(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        void commitRename(s.id);
                      } else if (e.key === 'Escape') {
                        setRenamingId('');
                      }
                    }}
                    onBlur={() => void commitRename(s.id)}
                  />
                ) : (
                  <b onDoubleClick={e => { e.stopPropagation(); startRename(s.id, s.title); }}>{s.title}</b>
                )}
                <small>
                  {(PERSONA_LABELS[s.persona] || s.persona)} · {s.message_count} 条{s.has_review ? ' · 有复盘' : ''}
                </small>
                <small>{s.updated_at ? new Date(s.updated_at * 1000).toLocaleString() : ''}</small>
                {s.tags.length > 0 && (
                  <span className="ws-item-tags">{s.tags.map(t => <em key={t}>{t}</em>)}</span>
                )}
                <span className="ws-item-actions">
                  <button
                    className="link-btn"
                    title="重命名（也可双击标题）"
                    onClick={e => {
                      e.stopPropagation();
                      startRename(s.id, s.title);
                    }}
                  >
                    重命名
                  </button>
                  <button
                    className="link-btn ws-del"
                    onClick={e => {
                      e.stopPropagation();
                      void removeSessionById(s.id);
                    }}
                  >
                    删除
                  </button>
                </span>
              </div>
            ))}
            {sessions.length === 0 && <p className="dialog-hint">还没有面试记录，点右侧「新建面试」开始。</p>}
          </div>
        </aside>

        <div className="ws-main">
          <div className="ws-bar">
            <input className="input ws-title" value={title} onChange={e => setTitle(e.target.value)} placeholder="本次面试标题（可改）" />
            <input
              className="input ws-tags-input"
              value={tagDraft}
              onChange={e => setTagDraft(e.target.value)}
              onBlur={commitTags}
              placeholder="标签：家电、区域经理、美的…（逗号分隔）"
            />
            <button className="btn btn-ghost btn-sm" onClick={() => void suggestTags()} disabled={busy}>AI 建议标签</button>
            <button className="btn btn-ghost btn-sm" onClick={() => void newSession()}>新建面试</button>
            <button className="btn btn-ghost btn-sm" onClick={() => void persist(sessionId)} disabled={busy}>保存</button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setSideCollapsed(v => !v)}
              title="折叠 / 展开左侧面试记录列表"
            >
              {sideCollapsed ? '展开记录列表' : '折叠记录列表'}
            </button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setConfigCollapsed(v => !v)}
              title="折叠 / 展开面试配置"
            >
              {configCollapsed ? '展开配置' : '折叠配置'}
            </button>
            <span className="form-hint">{savedHint}</span>
          </div>

          <section className={`card${configCollapsed ? ' collapsed-hidden' : ''}`}>
        <div className="form-grid">
          <div className="field">
            <label>面试官角色</label>
            <select className="input" value={persona} onChange={e => setPersona(e.target.value)}>
              {PERSONAS.map(p => (
                <option key={p.key} value={p.key}>{p.label}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>目标公司（可空）</label>
            <input className="input" value={company} onChange={e => setCompany(e.target.value)} placeholder="例如：美的（河南）" />
          </div>
          <div className="field">
            <label>语音对话</label>
            <label className="check">
              <input type="checkbox" checked={voiceOn} onChange={e => setVoiceOn(e.target.checked)} />
              面试官语音播报（edge-tts / 系统语音）
            </label>
            <label className="check">
              <input type="checkbox" checked={autoSubmit} onChange={e => setAutoSubmit(e.target.checked)} />
              识别完成自动提交回答
            </label>
            <label className="check">
              <input type="checkbox" checked={proofread} onChange={e => setProofread(e.target.checked)} />
              识别后轻校对（只纠错别字/行业词，不改语义）
            </label>
          </div>
          <div className="field">
            <label>面试官音色</label>
            <select className="input" value={voiceCfg.tts_voice} onChange={e => applyVoiceCfg({ tts_voice: e.target.value })}>
              {VOICE_OPTIONS.map(v => (
                <option key={v.value} value={v.value}>{v.label}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>语速</label>
            <select className="input" value={voiceCfg.tts_rate} onChange={e => applyVoiceCfg({ tts_rate: e.target.value })}>
              {RATE_OPTIONS.map(r => (
                <option key={r} value={r}>{r === '+0%' ? '正常' : r.replace('+', '加快 ').replace('-', '放慢 ')}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>识别模型（越准越慢）</label>
            <select className="input" value={voiceCfg.whisper_model} onChange={e => applyVoiceCfg({ whisper_model: e.target.value })}>
              {WHISPER_MODEL_OPTIONS.map(m => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>连续对话（免提）</label>
            <label className="check">
              <input
                type="checkbox"
                checked={continuous}
                onChange={e => (e.target.checked ? void startListening() : stopListening())}
              />
              VAD 自动断句（不用点按钮）
            </label>
            <label className="check">
              <input type="checkbox" checked={bargeIn} onChange={e => setBargeIn(e.target.checked)} />
              允许打断面试官（你一说话就打断）
            </label>
            <label className="check">
              <input type="checkbox" checked={showInterim} onChange={e => setShowInterim(e.target.checked)} />
              边说边显示识别文字（写入输入框，方便复盘）
            </label>
            <span className="form-hint">建议戴耳机：外放时回声可能被误判为你在说话</span>
          </div>
          <div className="field">
            <label>静音判定（停顿多久算说完）</label>
            <select className="input" value={silenceMs} onChange={e => setSilenceMs(Number(e.target.value))}>
              <option value={500}>0.5 秒（反应快）</option>
              <option value={800}>0.8 秒（推荐）</option>
              <option value={1200}>1.2 秒（不易误断）</option>
            </select>
          </div>
          <div className="field">
            <label>拾音灵敏度</label>
            <select className="input" value={sensitivity} onChange={e => setSensitivity(Number(e.target.value))}>
              <option value={1}>低（环境嘈杂）</option>
              <option value={1.2}>中（推荐）</option>
              <option value={1.6}>高（轻声说话）</option>
            </select>
          </div>
        </div>
        {voiceHint && <p className="dialog-hint">{voiceHint}</p>}
        <div className="field">
          <label>岗位 JD（从机会池复制，或手动粘贴；可空 = 按画像通用面试）</label>
          <textarea className="input" rows={3} value={jd} onChange={e => setJd(e.target.value)} placeholder="粘贴 JD 全文，面试官会据此提问" />
        </div>
        <div className="form-actions">
          <button className="btn btn-primary" onClick={start} disabled={busy}>
            {busy ? <Sparkles size={15} className="spin-once" /> : <Mic size={15} />}
            {messages.length ? '重新开始面试' : '开始面试'}
          </button>
          <button className="btn btn-ghost" onClick={() => runReview()} disabled={reviewBusy || !messages.length}>
            {reviewBusy ? <Sparkles size={15} className="spin-once" /> : <Square size={15} />}
            {reviewBusy ? '生成中…' : '结束并出复盘'}
          </button>
          <button className="btn btn-ghost" onClick={() => void newSession()} disabled={busy}>
            <RefreshCw size={15} /> 新建面试
          </button>
          <button className="btn btn-ghost" onClick={preview} title="用当前音色与语速试听一句">
            <VolumeX size={15} /> 试听音色
          </button>
          {speaking ? (
            <button className="btn btn-ghost btn-sm" onClick={stopSpeak}>
              <VolumeX size={13} /> 停止播报
            </button>
          ) : (
            <span className="form-hint">
              {progress ? `进度 ${progress} · ${finished ? '已结束' : '进行中'}` : '点击「开始面试」由面试官提问'}
            </span>
          )}
        </div>
        {err && <div className="callout callout-err">{err}</div>}
      </section>

      {messages.length > 0 && (
        <div className="chat-panel" style={{ marginTop: 12 }}>
          <div className="chat-top">
            <b>{PERSONAS.find(p => p.key === persona)?.label}</b>
            <span className="form-hint">{company || '未指定公司'} · {progress || '面试中'}</span>
            <span className="flex-spacer" />
            <span className="voice-status">
              <i className={`vdot${micHot ? ' hot' : ''}${speaking ? ' speaking' : ''}`} />
              {finished
                ? '面试已结束'
                : recState === 'transcribing'
                  ? '识别中…'
                  : busy
                    ? '面试官思考中…'
                    : speaking
                      ? '面试官说话中（可直接插话打断）'
                      : continuous
                        ? (micHot ? '正在听你说…' : '聆听中（停顿即提交）')
                        : '未开启连续对话'}
              <span className="vbar"><i style={{ width: `${Math.round(level * 100)}%` }} /></span>
            </span>
          </div>
          <div className="chat-msgs" ref={listRef}>
            {messages.map((m, i) => (
              <div key={i} className={`bubble ${m.role === 'user' ? 'bubble-user' : 'bubble-assistant'}`}>
                {m.content}
              </div>
            ))}
            {busy && <div className="bubble bubble-assistant typing">面试官思考中…</div>}
          </div>
          <div className="chat-inputbar">
            <button
              className={`btn ${continuous ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => (continuous ? stopListening() : void startListening())}
              disabled={finished}
              title="连续对话：直接说话，停顿自动提交；再点关闭"
            >
              {continuous ? <MicOff size={15} /> : <Mic size={15} />}
              {continuous ? '关闭连续对话' : '连续对话'}
            </button>
            <button
              className="btn btn-ghost"
              onClick={toggleRecord}
              disabled={busy || recState === 'transcribing' || finished || continuous}
              title="单次录音：点击开始，再点结束并识别"
            >
              {recState === 'transcribing' ? '识别中…' : '单次录音'}
            </button>
            <textarea
              className="input chat-input"
              rows={2}
              value={answer}
              onChange={e => setAnswer(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit();
              }}
              placeholder="可直接打字，或点左侧「语音回答」说话（Ctrl+Enter 提交）"
              disabled={busy || finished}
            />
            <button className="btn btn-primary" onClick={() => submit()} disabled={busy || !answer.trim() || finished}>
              <Send size={15} /> 提交
            </button>
          </div>
          {interimText && (micHot || recState === 'transcribing') && (
            <div className="interim-line">
              <span className="form-hint">实时识别：</span>
              {interimText}
            </div>
          )}
        </div>
      )}

      {reviewBusy && (
        <section className="progress">
          <Sparkles size={16} className="accent" />
          <span>正在生成面试复盘报告…</span>
          <div className="pbar"><i /></div>
        </section>
      )}

      {review && <ResultPanel title="面试复盘报告" text={review} badge="模拟面试" />}
        </div>
      </div>
    </div>
  );
}
