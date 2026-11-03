"""Ejecuta los casos de prueba y muestra las métricas.

Uso:  python -m scripts.evaluar            (recuperación + clasificación)
      python -m scripts.evaluar --con-llm  (incluye cobertura de la respuesta)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, evaluacion  # noqa: E402


async def main():
    r = await evaluacion.ejecutar(con_llm="--con-llm" in sys.argv)
    print(f"{'#':>2}  {'área':<4} {'rango':>5}  pregunta")
    for i, c in enumerate(r["casos"], 1):
        ok = "✓" if c["area_esperada"] == c["area_obtenida"] else "✗"
        print(f"{i:>2}  {ok:<4} {str(c['rango'] or '—'):>5}  {c['pregunta'][:70]}")
    print("\nResumen:")
    for k, v in r["resumen"].items():
        print(f"  {k:<22} {v}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        db.cerrar()
