"""Revisa que todo esté listo antes de ingestar o ejecutar Amparo.

Uso:  python -m scripts.diagnostico
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, voz  # noqa: E402

OK, MAL, AVISO = "✓", "✗", "!"


def version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("-")[0].split(".")[:3])
    except ValueError:
        return (0,)


def main() -> int:
    fallos = 0
    print(f"Ollama en {config.OLLAMA_URL}")
    try:
        v = httpx.get(f"{config.OLLAMA_URL}/api/version", timeout=3).json().get("version", "?")
        estado = OK if version(v) >= (0, 11, 10) else MAL
        fallos += estado == MAL
        print(f"  {estado} versión {v}" + ("" if estado == OK else "  → EmbeddingGemma requiere 0.11.10 o superior: actualice desde https://ollama.com/download"))
        modelos = [m["name"] for m in httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=3).json().get("models", [])]
        for nombre in (config.EMBED_MODELO, config.LLM_MODELO if config.LLM_PROVEEDOR == "ollama" else None):
            if not nombre:
                continue
            esta = any(m == nombre or m.split(":")[0] == nombre or m == f"{nombre}:latest" for m in modelos)
            fallos += not esta
            print(f"  {OK if esta else MAL} modelo {nombre}" + ("" if esta else f"  → ejecute: ollama pull {nombre}"))
        if not modelos:
            print("    (Ollama no tiene ningún modelo descargado)")
    except httpx.HTTPError:
        fallos += 1
        print(f"  {MAL} no responde  → abra la aplicación Ollama o ejecute: ollama serve")

    print(f"PostgreSQL en {config.DATABASE_URL.rsplit('@', 1)[-1]}")
    try:
        import psycopg
        with psycopg.connect(config.DATABASE_URL, connect_timeout=3) as conn:
            ext = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
            disp = conn.execute("SELECT 1 FROM pg_available_extensions WHERE name='vector'").fetchone()
            if ext:
                print(f"  {OK} conectado · pgvector {ext[0]}")
            elif disp:
                print(f"  {OK} conectado · pgvector disponible (se activa al ingestar)")
            else:
                fallos += 1
                print(f"  {MAL} conectado, pero sin pgvector  → use la imagen pgvector/pgvector:pg16 (docker compose up -d)")
    except Exception as e:  # noqa: BLE001
        fallos += 1
        print(f"  {MAL} sin conexión ({str(e).splitlines()[0][:120]})  → ejecute: docker compose up -d")

    print("Voz")
    print(f"  {OK if voz.stt_disponible() else AVISO} faster-whisper" + ("" if voz.stt_disponible() else "  (opcional: se usará el dictado del navegador)"))
    print(f"  {OK if voz.tts_disponible() else AVISO} Piper" + ("" if voz.tts_disponible() else "  (opcional: python -m scripts.descargar_voz)"))

    print("\nTodo listo." if not fallos else f"\n{fallos} problema(s) por resolver antes de ingestar.")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
