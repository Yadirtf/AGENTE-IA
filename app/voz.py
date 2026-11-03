"""Voz: STT con faster-whisper y TTS con Piper (ambos locales y en CPU).

Los modelos se cargan de forma perezosa la primera vez que se usan para que
el servidor arranque rápido. Si una librería no está instalada, el resto del
agente sigue funcionando (la interfaz usa la voz del navegador como respaldo).
"""
import io
import re
import threading
import time
import wave
from pathlib import Path

from . import config

_lock = threading.Lock()
_whisper = None
_piper = None


def stt_disponible() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def tts_disponible() -> bool:
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return Path(config.PIPER_VOZ).exists()


def _modelo_whisper():
    global _whisper
    with _lock:
        if _whisper is None:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel(config.WHISPER_MODELO, device="cpu", compute_type=config.WHISPER_COMPUTE)
    return _whisper


def transcribir(audio: bytes) -> dict:
    t0 = time.perf_counter()
    modelo = _modelo_whisper()
    segmentos, info = modelo.transcribe(
        io.BytesIO(audio), language="es", beam_size=1, vad_filter=True,
        initial_prompt="Consulta jurídica en Colombia: tutela, derecho de petición, EPS, arriendo, despido.")
    texto = " ".join(s.text.strip() for s in segmentos).strip()
    return {"texto": texto, "duracion_audio": round(info.duration, 2),
            "ms": round((time.perf_counter() - t0) * 1000)}


def _voz_piper():
    global _piper
    with _lock:
        if _piper is None:
            from piper import PiperVoice
            _piper = PiperVoice.load(config.PIPER_VOZ)
    return _piper


def limpiar_para_voz(texto: str) -> str:
    t = re.sub(r"\[\d+\]", "", texto)              # citas
    t = re.sub(r"[*_#`>]", "", t)                   # markdown
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.M)
    t = t.replace("art.", "artículo").replace("Art.", "Artículo")
    return re.sub(r"\s+", " ", t).strip()


def sintetizar(texto: str) -> bytes:
    voz = _voz_piper()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        if hasattr(voz, "synthesize_wav"):          # piper-tts >= 1.3
            voz.synthesize_wav(limpiar_para_voz(texto), wav)
        else:                                       # piper-tts 1.2
            voz.synthesize(limpiar_para_voz(texto), wav)
    return buf.getvalue()
