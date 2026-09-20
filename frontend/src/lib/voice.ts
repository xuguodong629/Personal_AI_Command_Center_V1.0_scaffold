// 语音对话能力：录音 → 本地 Whisper 识别；面试官回复 → edge-tts 合成
// 依赖不可用时前端自动降级：识别走浏览器 Web Speech（若支持），播报走系统语音。

const BASE = localStorage.getItem('jc-backend-url') || 'http://127.0.0.1:8787';

export interface VoiceStatus {
  stt: { available: boolean; model?: string; device?: string; error?: string };
  tts: { available: boolean; voice?: string; rate?: string; error?: string };
  config?: VoiceConfig;
}

export interface VoiceConfig {
  tts_voice: string;
  tts_rate: string;
  whisper_model: string;
  whisper_device: string;
  whisper_compute: string;
}

/** 常用中文音色（edge-tts） */
export const VOICE_OPTIONS = [
  { value: 'zh-CN-YunxiNeural', label: '男声 · 云希（自然，推荐）' },
  { value: 'zh-CN-YunjianNeural', label: '男声 · 云健（沉稳，压力面）' },
  { value: 'zh-CN-YunyangNeural', label: '男声 · 云扬（播报腔）' },
  { value: 'zh-CN-XiaoxiaoNeural', label: '女声 · 晓晓（亲和）' },
  { value: 'zh-CN-XiaoyiNeural', label: '女声 · 晓伊（年轻）' },
];

export const RATE_OPTIONS = ['-10%', '+0%', '+10%', '+20%', '+30%', '+40%'];

export const WHISPER_MODEL_OPTIONS = [
  { value: 'base', label: 'base（最快，准确率一般）' },
  { value: 'small', label: 'small（较快）' },
  { value: 'medium', label: 'medium（更准，推荐）' },
  { value: 'large-v3', label: 'large-v3（最准，CPU 很慢）' },
];

export async function fetchVoiceStatus(): Promise<VoiceStatus | null> {
  try {
    const res = await fetch(`${BASE}/api/voice/status`);
    if (!res.ok) return null;
    return (await res.json()) as VoiceStatus;
  } catch {
    return null;
  }
}

export async function saveVoiceConfig(cfg: VoiceConfig): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/api/voice/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** 转写轻校对：只修正同音字与行业术语，不改语义（失败则原样返回） */
export async function proofreadText(providerId: string, text: string): Promise<string> {
  try {
    const res = await fetch(`${BASE}/api/voice/proofread`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider_id: providerId, text }),
    });
    const data = (await res.json().catch(() => null)) as { ok?: boolean; text?: string } | null;
    return data?.ok && data.text ? data.text : text;
  } catch {
    return text;
  }
}

/** 音频 → 文本（后端本地 Whisper）。model 可临时指定更快的模型用于"边说边显示" */
export async function transcribe(
  blob: Blob,
  model?: string,
): Promise<{ ok: boolean; text?: string; error?: string }> {
  const url = model ? `${BASE}/api/voice/stt?model=${encodeURIComponent(model)}` : `${BASE}/api/voice/stt`;
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': blob.type || 'application/octet-stream' },
      body: blob,
    });
    const data = (await res.json().catch(() => null)) as { text?: string; detail?: string; error?: string } | null;
    if (!res.ok) return { ok: false, error: data?.detail || data?.error || `HTTP ${res.status}` };
    return { ok: true, text: data?.text || '' };
  } catch (e) {
    return { ok: false, error: `无法连接后端：${(e as Error).message}` };
  }
}

/** 文本 → mp3 的 blob URL（后端 edge-tts）；失败返回 null */
export async function synthesize(text: string, voice?: string, rate?: string): Promise<string | null> {
  try {
    const res = await fetch(`${BASE}/api/voice/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice: voice || '', rate: rate || '' }),
    });
    if (!res.ok) return null;
    const blob = await res.blob();
    if (!blob.size) return null;
    return URL.createObjectURL(blob);
  } catch {
    return null;
  }
}

/** 录音器：MediaRecorder → webm/opus（后端 PyAV 解码，无需 ffmpeg） */
export class Recorder {
  private mediaRecorder: MediaRecorder | null = null;
  private chunks: BlobPart[] = [];
  private stream: MediaStream | null = null;

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.chunks = [];
    const mr = new MediaRecorder(this.stream);
    mr.ondataavailable = e => {
      if (e.data && e.data.size) this.chunks.push(e.data);
    };
    mr.start();
    this.mediaRecorder = mr;
  }

  stop(): Promise<Blob> {
    return new Promise(resolve => {
      const mr = this.mediaRecorder;
      if (!mr) {
        resolve(new Blob());
        return;
      }
      mr.onstop = () => {
        const blob = new Blob(this.chunks, { type: mr.mimeType || 'audio/webm' });
        this.stream?.getTracks().forEach(t => t.stop());
        this.stream = null;
        this.mediaRecorder = null;
        resolve(blob);
      };
      mr.stop();
    });
  }

  cancel(): void {
    try {
      this.mediaRecorder?.stop();
    } catch {
      /* ignore */
    }
    this.stream?.getTracks().forEach(t => t.stop());
    this.stream = null;
    this.mediaRecorder = null;
  }
}

/** 系统语音兜底朗读（edge-tts 不可用时） */
export function speakLocal(text: string): void {
  if (typeof window === 'undefined' || !window.speechSynthesis) return;
  const clean = text.replace(/【[^】]*】/g, ' ').replace(/\s+/g, ' ').trim();
  if (!clean) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(clean.slice(0, 500));
  u.lang = 'zh-CN';
  u.rate = 1.02;
  window.speechSynthesis.speak(u);
}

/** 把长文本切成适合逐句播报的短句（首句尽快出声，保留自然停顿） */
export function splitSentences(text: string): string[] {
  const clean = text.replace(/【[^】]*】/g, ' ').replace(/\r/g, '').trim();
  const parts = clean
    .split(/(?<=[。！？；!?;])|\n+/)
    .map(s => s.trim())
    .filter(Boolean);
  const out: string[] = [];
  for (const p of parts) {
    if (p.length <= 60) {
      out.push(p);
      continue;
    }
    let buf = '';
    for (const seg of p.split(/(?<=[，,、])/)) {
      if ((buf + seg).length > 60 && buf) {
        out.push(buf);
        buf = seg;
      } else {
        buf += seg;
      }
    }
    if (buf) out.push(buf);
  }
  return out.length ? out : [clean];
}

/** 分句流式播报队列：首句先出声、边播边合成后续；支持随时打断 */
export class SpeechQueue {
  private queue: string[] = [];
  private running = false;
  private stopped = false;
  private audio: HTMLAudioElement | null = null;
  private voice: string;
  private rate: string;
  private onState: (speaking: boolean) => void;

  constructor(opts: { voice?: string; rate?: string; onState?: (speaking: boolean) => void } = {}) {
    this.voice = opts.voice || '';
    this.rate = opts.rate || '';
    this.onState = opts.onState || (() => {});
  }

  setVoice(voice: string, rate: string): void {
    this.voice = voice;
    this.rate = rate;
  }

  push(text: string): void {
    this.queue.push(...splitSentences(text));
    this.stopped = false;
    void this.drain();
  }

  /** 打断：立即停止播放并清空队列 */
  stop(): void {
    this.stopped = true;
    this.queue = [];
    if (this.audio) {
      this.audio.pause();
      this.audio = null;
    }
    window.speechSynthesis?.cancel();
    this.running = false;
    this.onState(false);
  }

  get speaking(): boolean {
    return this.running;
  }

  private async drain(): Promise<void> {
    if (this.running) return;
    this.running = true;
    this.onState(true);
    try {
      while (this.queue.length && !this.stopped) {
        const sentence = this.queue.shift()!;
        const url = await synthesize(sentence, this.voice, this.rate);
        if (this.stopped) {
          if (url) URL.revokeObjectURL(url);
          break;
        }
        if (!url) {
          speakLocal(sentence);
          continue;
        }
        await this.play(url);
      }
    } finally {
      this.running = false;
      if (!this.stopped) this.onState(false);
    }
  }

  private play(url: string): Promise<void> {
    return new Promise(resolve => {
      const audio = new Audio(url);
      this.audio = audio;
      const done = () => {
        URL.revokeObjectURL(url);
        if (this.audio === audio) this.audio = null;
        resolve();
      };
      audio.onended = done;
      audio.onerror = done;
      audio.play().catch(done);
    });
  }
}

export interface ListenerOptions {
  /** 静音多久判定说完（毫秒，默认 800） */
  silenceMs?: number;
  /** 灵敏度：1=低（抗噪）…1.6=高（灵敏），默认 1.2 */
  sensitivity?: number;
  /** 播报期间阈值放大倍数（抑制外放回声误触发），默认 1.8 */
  echoGuard?: number;
  /** 边说边显示的间隔（毫秒；0/未设置 = 关闭） */
  interimMs?: number;
  onSpeechStart?: () => void;
  onUtterance?: (blob: Blob) => void;
  /** 说话过程中的增量音频（累计至今，含容器头，可独立解码），用于实时显示识别文字 */
  onInterim?: (blob: Blob) => void;
  onLevel?: (level: number, state: 'silence' | 'speech') => void;
  onError?: (msg: string) => void;
}

/**
 * 连续聆听器：基于 Web Audio 能量 VAD 自动断句。
 * 说话即自动录音；停顿超过 silenceMs 自动产出音频片段；播放期间仍监听以支持打断。
 */
export class ContinuousListener {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private analyser: AnalyserNode | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: BlobPart[] = [];
  private timer: number | null = null;
  private interimTimer: number | null = null;
  private speaking = false;
  private silenceFrames = 0;
  private loudFrames = 0;
  private noiseFloor = 0.01;
  private calibrateFrames = 0;
  private buf: Float32Array<ArrayBuffer> | null = null;
  private opts: ListenerOptions;
  private active = false;
  /** 播报中（提高阈值防外放回声） */
  playing = false;

  constructor(opts: ListenerOptions = {}) {
    this.opts = opts;
  }

  get listening(): boolean {
    return this.active;
  }

  async start(): Promise<void> {
    if (this.active) return;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      this.opts.onError?.(`无法访问麦克风：${(e as Error).message}`);
      return;
    }
    const Ctor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new Ctor();
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    src.connect(this.analyser);
    this.buf = new Float32Array(new ArrayBuffer(this.analyser.fftSize * 4));
    this.active = true;
    this.calibrateFrames = 12;
    this.timer = window.setInterval(() => this.tick(), 50);
  }

  stop(): void {
    this.active = false;
    if (this.timer !== null) {
      window.clearInterval(this.timer);
      this.timer = null;
    }
    try {
      if (this.recorder?.state === 'recording') this.recorder.stop();
    } catch {
      /* ignore */
    }
    this.recorder = null;
    this.stream?.getTracks().forEach(t => t.stop());
    this.stream = null;
    void this.ctx?.close();
    this.ctx = null;
    this.analyser = null;
    this.speaking = false;
  }

  private rms(): number {
    if (!this.analyser || !this.buf) return 0;
    this.analyser.getFloatTimeDomainData(this.buf);
    let sum = 0;
    for (let i = 0; i < this.buf.length; i++) sum += this.buf[i] * this.buf[i];
    return Math.sqrt(sum / this.buf.length);
  }

  private startRecording(): void {
    if (!this.stream) return;
    this.chunks = [];
    const mr = new MediaRecorder(this.stream);
    mr.ondataavailable = e => {
      if (e.data && e.data.size) this.chunks.push(e.data);
    };
    mr.start();
    this.recorder = mr;
    // 边说边显示：每隔 interimMs 把"累计音频"交给上层做增量识别（含容器头，可独立解码）
    if (this.opts.interimMs && this.opts.onInterim) {
      const type = mr.mimeType || 'audio/webm';
      this.interimTimer = window.setInterval(() => {
        if (!this.chunks.length) return;
        try {
          this.opts.onInterim?.(new Blob([...this.chunks], { type }));
        } catch {
          /* ignore */
        }
      }, this.opts.interimMs);
    }
    this.opts.onSpeechStart?.();
  }

  private finishRecording(): void {
    if (this.interimTimer !== null) {
      window.clearInterval(this.interimTimer);
      this.interimTimer = null;
    }
    const mr = this.recorder;
    const chunks = this.chunks;
    this.recorder = null;
    if (!mr) return;
    mr.onstop = () => {
      const blob = new Blob(chunks, { type: mr.mimeType || 'audio/webm' });
      if (blob.size > 1200) this.opts.onUtterance?.(blob);
    };
    try {
      mr.stop();
    } catch {
      /* ignore */
    }
  }

  private tick(): void {
    if (!this.active) return;
    const level = this.rms();
    const sens = this.opts.sensitivity ?? 1.2;
    const guard = this.playing ? (this.opts.echoGuard ?? 1.8) : 1;

    if (this.calibrateFrames > 0) {
      this.noiseFloor = Math.max(this.noiseFloor * 0.7 + level * 0.3, 0.002);
      this.calibrateFrames--;
      this.opts.onLevel?.(level, 'silence');
      return;
    }

    const threshold = Math.max(0.012, this.noiseFloor * 2.6) * sens * guard;
    const isSpeech = level > threshold;

    if (!this.speaking) {
      this.loudFrames = isSpeech ? this.loudFrames + 1 : 0;
      // 连续 3 帧（≈150ms）才算说话，避免咳嗽/噪声误触发
      if (this.loudFrames >= 3) {
        this.speaking = true;
        this.silenceFrames = 0;
        this.startRecording();
      }
    } else {
      this.silenceFrames = isSpeech ? 0 : this.silenceFrames + 1;
      const need = Math.ceil((this.opts.silenceMs ?? 800) / 50);
      if (this.silenceFrames >= need) {
        this.speaking = false;
        this.loudFrames = 0;
        this.finishRecording();
      }
    }
    this.opts.onLevel?.(level, this.speaking ? 'speech' : 'silence');
  }
}
