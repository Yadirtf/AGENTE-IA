"""Descarga la voz en español para Piper (TTS local).

Uso:  python -m scripts.descargar_voz [nombre_voz]
Voces sugeridas: es_MX-claude-high (por defecto), es_MX-ald-medium, es_ES-davefx-medium
"""
import sys
import urllib.request
from pathlib import Path

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/{loc}/{nombre}/{calidad}/{archivo}"
DESTINO = Path(__file__).resolve().parent.parent / "modelos"


def main():
    voz = sys.argv[1] if len(sys.argv) > 1 else "es_MX-claude-high"
    loc, nombre, calidad = voz.split("-")
    DESTINO.mkdir(exist_ok=True)
    for archivo in (f"{voz}.onnx", f"{voz}.onnx.json"):
        url = BASE.format(loc=loc, nombre=nombre, calidad=calidad, archivo=archivo)
        print("↓", url)
        urllib.request.urlretrieve(url, DESTINO / archivo)
    print(f"Voz guardada en {DESTINO}. Configure PIPER_VOZ={DESTINO / (voz + '.onnx')}")


if __name__ == "__main__":
    main()
