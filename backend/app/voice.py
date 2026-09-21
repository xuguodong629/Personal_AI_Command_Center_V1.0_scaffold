"""语音模块：本地 Whisper 识别（STT）+ edge-tts 合成（TTS）。

设计要点：
- 识别用 faster-whisper（本地、离线、隐私好）；模型懒加载并常驻内存。
- 合成用 edge-tts（微软在线语音，免费、中文自然）；失败时前端回退系统朗读。
- 依赖缺失时接口返回明确指引，不影响文字模式使用。
- 音频解码交给 faster-whisper 内置的 PyAV，无需系统 ffmpeg。

可选环境变量：
- AIOS_WHISPER_MODEL  默认 small（可 tiny/base/small/medium）
- AIOS_WHISPER_DEVICE 默认 cpu（有 NVIDIA 显卡可设 cuda）
- AIOS_WHISPER_COMPUTE 默认 int8
- HF_ENDPOINT        国内可设 https://hf-mirror.com 加速模型下载
"""
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter(prefix="/api/voice")

# 模型下载到项目内（可移植、便于打包；避免占用用户目录缓存）
MODEL_DIR = Path(os.getenv("AIOS_WHISPER_DIR", str(Path(__file__).resolve().parents[2] / "data" / "models" / "whisper")))
VOICE_FILE = Path(__file__).resolve().parents[2] / "data" / "config" / "voice.json"

# 首次使用需从 HuggingFace 下载模型；国内直连常失败，未显式配置时默认走镜像。
# 如需改回官方源：设置环境变量 HF_ENDPOINT=https://huggingface.co
if not os.getenv("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 模型缓存/日志统一放项目内（可移植、可打包；也避免写入用户目录受限）
_HF_HOME = Path(__file__).resolve().parents[2] / "data" / "models" / "hf"
os.environ.setdefault("HF_HOME", str(_HF_HOME))
# 禁用 Xet 传输：部分环境（受限权限/代理）下会报 I/O error，退回普通 HTTP 下载更稳
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

DEFAULT_TTS_VOICE = os.getenv("AIOS_TTS_VOICE", "zh-CN-YunxiNeural")  # 男声（云希）
DEFAULT_TTS_RATE = os.getenv("AIOS_TTS_RATE", "+20%")                 # 语速偏快


class VoiceConfig(BaseModel):
    tts_voice: str = DEFAULT_TTS_VOICE
    tts_rate: str = DEFAULT_TTS_RATE
    whisper_model: str = "small"    # tiny/base/small/medium/large-v3：越大越准越慢（medium 约 2× 实时）
    whisper_device: str = "cpu"
    whisper_compute: str = "int8"


def _load_voice_cfg() -> VoiceConfig:
    if not VOICE_FILE.exists():
        return VoiceConfig()
    try:
        return VoiceConfig(**json.loads(VOICE_FILE.read_text("utf-8-sig")))
    except Exception:
        return VoiceConfig()


def _save_voice_cfg(cfg: VoiceConfig) -> None:
    VOICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    VOICE_FILE.write_text(cfg.model_dump_json(indent=2), "utf-8")


# 行业术语提示词：显著提升中文专有词识别率
STT_PROMPT = (
    "以下是普通话面试对话，涉及家电、厨卫、净水、渠道、经销商、代理商、回款、账期、"
    "动销、库存、单店模型、县域下沉、KA、区域经理、美的、海尔、格力、海信等词汇。"
)

_models: dict[str, Any] = {}     # 按 模型|设备|精度 缓存（支持临时切换轻量模型）
_model_lock = threading.Lock()
_model_error = ""


def _get_model(model_override: str = ""):
    """懒加载 faster-whisper 模型（按 模型|设备|精度 缓存）。
    model_override 用于"边说边显示"时临时换用更快的模型；首次调用会下载模型。"""
    global _model_error
    cfg = _load_voice_cfg()
    name = model_override or cfg.whisper_model
    key = f"{name}|{cfg.whisper_device}|{cfg.whisper_compute}"
    if key in _models:
        return _models[key]
    with _model_lock:
        if key in _models:
            return _models[key]
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as e:  # 依赖未安装
            _model_error = f"未安装 faster-whisper（{e}）。请双击「安装语音依赖.bat」后重启后端。"
            return None
        try:
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            _models[key] = WhisperModel(
                name,
                device=cfg.whisper_device,
                compute_type=cfg.whisper_compute,
                download_root=str(MODEL_DIR),
            )
            _model_error = ""
        except Exception as e:
            _model_error = (
                f"Whisper 模型（{name}）加载失败：{e}。首次使用需联网下载模型"
                f"（存放于 {MODEL_DIR}）；国内默认走 hf-mirror 镜像。"
            )
            return None
    return _models[key]


@router.get("/config")
def get_voice_config():
    return {"ok": True, "config": _load_voice_cfg().model_dump()}


@router.post("/config")
def set_voice_config(cfg: VoiceConfig):
    _save_voice_cfg(cfg)
    return {"ok": True, "config": cfg.model_dump()}


@router.get("/status")
def voice_status():
    """前端据此决定是否显示语音按钮。"""
    try:
        import edge_tts  # type: ignore  # noqa: F401
        tts_ok = True
        tts_err = ""
    except Exception as e:
        tts_ok = False
        tts_err = f"未安装 edge-tts（{e}）"

    try:
        import faster_whisper  # type: ignore  # noqa: F401
        stt_ok = True
    except Exception:
        stt_ok = False

    cfg = _load_voice_cfg()
    return {
        "ok": True,
        "stt": {"available": stt_ok, "model": cfg.whisper_model, "device": cfg.whisper_device, "error": _model_error},
        "tts": {"available": tts_ok, "voice": cfg.tts_voice, "rate": cfg.tts_rate, "error": tts_err},
        "config": cfg.model_dump(),
    }


@router.post("/stt")
async def speech_to_text(request: Request, language: str = "zh", model: str = ""):
    """音频 → 文本。请求体为原始音频字节（webm/opus 或 wav），免 multipart 依赖。
    model 可临时切换识别模型（"边说边显示"用 base 更快）；不传则用配置模型。"""
    whisper = _get_model(model)
    if whisper is None:
        raise HTTPException(status_code=503, detail=_model_error or "语音识别不可用")

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="音频为空")

    # 依据魔数判断容器格式，便于 PyAV 正确解码
    suffix = ".webm"
    if data[:4] == b"RIFF":
        suffix = ".wav"
    elif data[:4] == b"OggS":
        suffix = ".ogg"
    elif data[4:8] == b"ftyp":
        suffix = ".m4a"

    tmp_path = ""
    started = time.time()
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        segments, info = whisper.transcribe(
            tmp_path,
            language=language or None,
            vad_filter=True,
            # 提升中文口语准确率的关键参数组合
            beam_size=5,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 300},
            initial_prompt=STT_PROMPT,
        )
        text = "".join(seg.text for seg in segments).strip()
        return {
            "ok": True,
            "text": text,
            "duration_ms": int(getattr(info, "duration", 0) * 1000),
            "latency_ms": int((time.time() - started) * 1000),
            "model": model or _load_voice_cfg().whisper_model,
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


class TTSRequest(BaseModel):
    text: str = ""
    voice: str = ""
    rate: str = "+0%"


@router.post("/tts")
async def text_to_speech(req: TTSRequest):
    """文本 → mp3（edge-tts 在线合成）。"""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本为空")
    try:
        import edge_tts  # type: ignore
    except Exception:
        raise HTTPException(status_code=503, detail="未安装 edge-tts，请双击「安装语音依赖.bat」后重启后端")

    cfg = _load_voice_cfg()
    voice = req.voice or cfg.tts_voice
    rate = req.rate or cfg.tts_rate or "+0%"
    try:
        communicate = edge_tts.Communicate(text[:1200], voice, rate=rate)
        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                audio.extend(chunk["data"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"语音合成失败（可能网络不通）：{e}")
    if not audio:
        raise HTTPException(status_code=502, detail="语音合成返回空音频")
    return Response(content=bytes(audio), media_type="audio/mpeg")


# ---------- 转写轻校对（可选）：只修正同音字/行业术语，不改语义 ----------

class ProofreadRequest(BaseModel):
    provider_id: str
    text: str = ""


@router.post("/proofread")
async def proofread(req: ProofreadRequest):
    text = (req.text or "").strip()
    if not text:
        return {"ok": True, "text": ""}
    try:
        from app.ai import _llm_call, _load_providers  # 复用直连模型调用
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"无法加载模型模块：{e}")

    provider = next((p for p in _load_providers() if p.id == req.provider_id), None)
    if not provider:
        raise HTTPException(status_code=400, detail="模型不存在或已被删除")

    sys_prompt = (
        "你是语音转写校对员。只修正同音字、错别字、行业术语与标点；"
        "必须保留说话人的口语原样与全部信息，不得增删内容、不得改写语气、不得总结。"
        "只输出校对后的文本本身，不要任何解释。"
    )
    user = (
        f"原始转写：\n{text}\n\n"
        "行业词表（优先按此纠错）：家电、厨卫、净水、渠道、经销商、代理商、回款、账期、动销、"
        "库存、单店模型、县域下沉、KA、区域经理、美的、海尔、格力、海信、TCL、老板电器、方太。"
    )
    r = await _llm_call(provider, [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user},
    ])
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error", "校对失败"), "text": text}
    return {"ok": True, "text": (r["content"] or text).strip(), "model": provider.model}
