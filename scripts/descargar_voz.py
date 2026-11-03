"""Descarga voces en español para Piper (TTS local, CPU).

Uso:
  python -m scripts.descargar_voz                  # voz por defecto (es_MX-claude-high)
  python -m scripts.descargar_voz es_AR-daniela-high es_MX-ald-medium
  python -m scripts.descargar_voz --todas          # todas las voces del catálogo (~460 MB)
  python -m scripts.descargar_voz --lista          # muestra el catálogo

Las voces quedan en la carpeta modelos/ y aparecen solas en el botón «🎙 Voz» de la interfaz.
"""
import sys
import urllib.request
from pathlib import Path

from app.voz import CATALOGO

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/{loc}/{nombre}/{calidad}/{archivo}"
DESTINO = Path(__file__).resolve().parent.parent / "modelos"


def descargar(voz: str) -> None:
    loc, nombre, calidad = voz.split("-")
    DESTINO.mkdir(exist_ok=True)
    for archivo in (f"{voz}.onnx.json", f"{voz}.onnx"):
        destino = DESTINO / archivo
        if destino.exists() and destino.stat().st_size > 1000:
            print("✓ ya existe", archivo)
            continue
        url = BASE.format(loc=loc, nombre=nombre, calidad=calidad, archivo=archivo)
        print("↓", url)
        urllib.request.urlretrieve(url, destino)


def main():
    args = sys.argv[1:]
    if "--lista" in args:
        for k, v in CATALOGO.items():
            print(f"  {k:24} {v['genero']:22} {v['acento']:10} {v['mb']:>4} MB  {v['desc']}")
        return
    voces = list(CATALOGO) if "--todas" in args else (args or ["es_MX-claude-high"])
    for voz in voces:
        try:
            descargar(voz)
        except Exception as e:  # noqa: BLE001
            print(f"✗ No se pudo descargar {voz}: {e}")
    print(f"Listo. Voces en {DESTINO}. Reinicie uvicorn y elíjalas en el botón «🎙 Voz».")


if __name__ == "__main__":
    main()
