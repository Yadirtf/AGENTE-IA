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
_whisper: dict = {}


def stt_disponible() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _modelo_whisper(nombre: str | None = None):
    """Carga perezosa; la llamada en vivo usa un modelo más rápido (WHISPER_LLAMADA) que la consulta."""
    nombre = nombre or config.WHISPER_MODELO
    with _lock:
        if nombre not in _whisper:
            from faster_whisper import WhisperModel
            _whisper[nombre] = WhisperModel(nombre, device="cpu", compute_type=config.WHISPER_COMPUTE)
    return _whisper[nombre]


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


def transcribir(audio: bytes, modelo_nombre: str | None = None) -> dict:
    t0 = time.perf_counter()
    modelo = _modelo_whisper(modelo_nombre)
    muestras = decodificar_audio(audio)
    if muestras.size < 1600:                                # menos de 0,1 s de audio
        return {"texto": "", "duracion_audio": 0, "ms": round((time.perf_counter() - t0) * 1000)}
    segmentos, info = modelo.transcribe(
        muestras, language="es", beam_size=1, vad_filter=True,
        initial_prompt="Consulta jurídica en Colombia: tutela, derecho de petición, EPS, arriendo, despido.")
    texto = " ".join(s.text.strip() for s in segmentos).strip()
    return {"texto": texto, "duracion_audio": round(info.duration, 2),
            "ms": round((time.perf_counter() - t0) * 1000)}


# ---------------------------------------------------------------------------
# TTS: varias voces de Piper y prosodia por emoción
# ---------------------------------------------------------------------------
# Voces en español de rhasspy/piper-voices que funcionan bien en CPU.
CATALOGO = {
    "es_MX-claude-high": {"nombre": "Claude", "acento": "México", "genero": "femenina", "calidad": "alta", "mb": 114,
                          "desc": "Clara y cercana (por defecto)"},
    "es_AR-daniela-high": {"nombre": "Daniela", "acento": "Argentina", "genero": "femenina", "calidad": "alta", "mb": 114,
                           "desc": "Cálida y expresiva"},
    "es_MX-ald-medium": {"nombre": "Ald", "acento": "México", "genero": "masculina", "calidad": "media", "mb": 63,
                         "desc": "Serena y amable"},
    "es_ES-davefx-medium": {"nombre": "Dave", "acento": "España", "genero": "masculina", "calidad": "media", "mb": 63,
                            "desc": "Firme y clara"},
    "es_ES-sharvard-medium": {"nombre": "Sharvard", "acento": "España", "genero": "femenina y masculina", "calidad": "media",
                              "mb": 77, "desc": "Dos voces en un mismo modelo"},
    "es_ES-carlfm-x_low": {"nombre": "Carlos", "acento": "España", "genero": "masculina", "calidad": "ligera", "mb": 28,
                           "desc": "Muy liviana, ideal para PCs lentos"},
}
_HABLANTE = {"F": ("femenina", "voz femenina"), "M": ("masculina", "voz masculina")}

# Piper no tiene "emociones", pero sí controla ritmo (length_scale) y variación (noise).
# El tono se sube o baja remuestreando el audio de cada frase. Con eso, y con pausas
# distintas entre frases, la voz deja de sonar plana.
PROSODIA = {
    #             ritmo  variación  duración-fonema  tono   volumen  pausa(ms)
    "alegre":    (0.93,  0.78,      0.95,            1.06,  1.00,    260),
    "animada":   (0.95,  0.74,      0.90,            1.04,  1.00,    240),
    "calida":    (1.06,  0.66,      0.85,            1.01,  0.94,    330),
    "tranquila": (1.08,  0.60,      0.80,            0.99,  0.92,    360),
    "seria":     (1.04,  0.50,      0.70,            0.96,  1.00,    420),
}

_voces: dict = {}


def voces_instaladas() -> list[dict]:
    """Voces presentes en la carpeta modelos/, con sus hablantes si el modelo tiene varios."""
    import json
    lista = []
    defecto = Path(config.PIPER_VOZ).stem
    for onnx in sorted(config.MODELOS.glob("*.onnx")):
        js = onnx.with_suffix(".onnx.json")
        if not js.exists():
            continue
        try:
            meta = json.loads(js.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        base = {"id": onnx.stem, "nombre": onnx.stem.split("-")[1].capitalize(), "acento": "", "genero": "",
                "calidad": onnx.stem.split("-")[-1], "desc": "", **CATALOGO.get(onnx.stem, {})}
        base["defecto"] = onnx.stem == defecto
        hablantes = meta.get("speaker_id_map") or {}
        if len(hablantes) > 1:
            for clave in hablantes:
                genero, desc = _HABLANTE.get(clave.upper(), ("", f"hablante {clave}"))
                lista.append({**base, "id": f"{onnx.stem}#{clave}", "nombre": f"{base['nombre']} {clave}",
                              "genero": genero or base["genero"], "desc": desc, "defecto": False})
        else:
            lista.append(base)
    lista.sort(key=lambda v: (not v["defecto"], v["id"]))
    return lista


def catalogo() -> list[dict]:
    instaladas = {v["id"].split("#")[0] for v in voces_instaladas()}
    return [{"id": k, **v, "instalada": k in instaladas} for k, v in CATALOGO.items()]


def _resolver(voz_id: str | None) -> tuple[Path, str | None]:
    modelo, _, hablante = (voz_id or "").partition("#")
    if modelo and re.fullmatch(r"[\w\-]+", modelo):
        ruta = config.MODELOS / f"{modelo}.onnx"
        if ruta.exists():
            return ruta, hablante or None
    return Path(config.PIPER_VOZ), None


def _voz_piper(ruta: Path):
    from piper import PiperVoice
    clave = str(ruta)
    with _lock:
        if clave not in _voces:
            if len(_voces) >= 3:                       # cada voz ocupa 60-120 MB: se guardan 3 como máximo
                _voces.pop(next(iter(_voces)))
            _voces[clave] = PiperVoice.load(clave)
    return _voces[clave]


def limpiar_para_voz(texto: str) -> str:
    t = re.sub(r"\[\d+\]", "", texto)              # citas
    t = re.sub(r"[*_#`>]", "", t)                   # markdown
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.M)
    t = re.sub(r"[\U0001F000-\U0001FFFF☀-➿️]", "", t)   # emojis
    t = t.replace("art.", "artículo").replace("Art.", "Artículo").replace("C.C.", "cédula")
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _frase_pcm(voz, texto: str, emocion: str, velocidad: float, hablante: str | None):
    """Sintetiza una frase con la prosodia de su emoción. Devuelve (muestras int16, frecuencia)."""
    import numpy as np

    ritmo, ruido, ruido_w, tono, volumen, _ = PROSODIA.get(emocion, PROSODIA["tranquila"])
    cfg_voz = getattr(voz, "config", None)
    base = getattr(cfg_voz, "length_scale", 1.0) or 1.0
    # Se alarga primero en el factor de tono; al remuestrear para subir el tono vuelve a la duración deseada.
    largo = base * ritmo * tono / max(0.6, min(1.6, velocidad))
    sid = None
    if hablante is not None:
        mapa = getattr(cfg_voz, "speaker_id_map", None) or {}
        sid = mapa.get(hablante, int(hablante) if str(hablante).isdigit() else None)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        if hasattr(voz, "synthesize_wav"):                         # piper-tts >= 1.3
            from piper import SynthesisConfig
            voz.synthesize_wav(texto, wav, syn_config=SynthesisConfig(
                speaker_id=sid, length_scale=largo, noise_scale=ruido, noise_w_scale=ruido_w, volume=volumen))
        else:                                                      # piper-tts 1.2
            voz.synthesize(texto, wav, speaker_id=sid, length_scale=largo, noise_scale=ruido, noise_w=ruido_w)
    buf.seek(0)
    with wave.open(buf, "rb") as w:
        sr = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    if abs(tono - 1) > 0.005 and pcm.size:
        n = int(pcm.size / tono)
        pcm = np.interp(np.linspace(0, pcm.size - 1, n), np.arange(pcm.size), pcm)
    if not hasattr(voz, "synthesize_wav"):
        pcm *= volumen
    rampa = min(240, pcm.size // 4)                                # evita "clics" entre frases
    if rampa:
        pcm[:rampa] *= np.linspace(0, 1, rampa)
        pcm[-rampa:] *= np.linspace(1, 0, rampa)
    return np.clip(pcm, -32768, 32767).astype(np.int16), sr


def sintetizar_segmentos(segmentos: list[dict], voz_id: str | None = None, velocidad: float = 1.0) -> tuple[bytes, list[int]]:
    """Une las frases con pausas naturales. Devuelve el WAV y la duración de cada frase (ms) para los subtítulos."""
    import numpy as np

    ruta, hablante = _resolver(voz_id)
    voz = _voz_piper(ruta)
    partes, duraciones, sr = [], [], 22050
    for s in segmentos:
        texto = limpiar_para_voz(s.get("texto", ""))
        if not texto:
            continue
        pcm, sr = _frase_pcm(voz, texto, s.get("emocion", "tranquila"), velocidad, hablante)
        pausa = np.zeros(int(sr * PROSODIA.get(s.get("emocion"), PROSODIA["tranquila"])[5] / 1000), dtype=np.int16)
        partes += [pcm, pausa]
        duraciones.append(round((pcm.size + pausa.size) / sr * 1000))
    audio = np.concatenate(partes) if partes else np.zeros(0, dtype=np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(audio.tobytes())
    return buf.getvalue(), duraciones


def tts_disponible() -> bool:
    """Basta con que Piper esté instalado y haya al menos una voz en modelos/."""
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return Path(config.PIPER_VOZ).exists() or bool(voces_instaladas())
