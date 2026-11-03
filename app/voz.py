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


def decodificar_audio(audio: bytes, frecuencia: int = 16000):
    """Convierte el audio del navegador (WebM/Opus, OGG, WAV…) a float32 mono de 16 kHz.

    Se decodifica aquí con PyAV en lugar de dejarlo a faster-whisper, porque las
    versiones recientes de PyAV (≥ 15) eliminaron el argumento `metadata_errors`
    que usa faster-whisper 1.2 y la transcripción fallaba con un TypeError.
    """
    import av
    import numpy as np

    remuestreo = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=frecuencia)
    partes = []
    with av.open(io.BytesIO(audio), mode="r") as contenedor:
        for cuadro in contenedor.decode(audio=0):
            for salida in remuestreo.resample(cuadro):
                partes.append(salida.to_ndarray().reshape(-1))
        for salida in remuestreo.resample(None):          # vacía el búfer final
            partes.append(salida.to_ndarray().reshape(-1))
    if not partes:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(partes).astype(np.float32) / 32768.0


def transcribir(audio: bytes) -> dict:
    t0 = time.perf_counter()
    modelo = _modelo_whisper()
    muestras = decodificar_audio(audio)
    if muestras.size < 1600:                                # menos de 0,1 s de audio
        return {"texto": "", "duracion_audio": 0, "ms": round((time.perf_counter() - t0) * 1000)}
    segmentos, info = modelo.transcribe(
        muestras, language="es", beam_size=1, vad_filter=True,
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
