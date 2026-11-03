"""Ingesta de la base de conocimiento: crea el esquema, carga catálogos,
divide los documentos en fragmentos (chunks), genera embeddings con
EmbeddingGemma y los guarda en PostgreSQL + pgvector.

Uso:  python -m scripts.ingestar
"""
import asyncio
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, db, llm  # noqa: E402

MAX_CARACTERES = 900


def leer(ruta: Path) -> tuple[dict, str]:
    texto = ruta.read_text(encoding="utf-8")
    meta = {}
    m = re.match(r"^---\n(.*?)\n---\n", texto, re.S)
    if m:
        for linea in m.group(1).splitlines():
            k, _, v = linea.partition(":")
            meta[k.strip()] = v.strip()
        texto = texto[m.end():]
    return meta, texto


def fragmentar(texto: str) -> list[tuple[str, str]]:
    """Un fragmento por sección '## '. Las secciones largas se dividen por
    párrafos/oraciones con solapamiento de una oración."""
    salida = []
    for bloque in re.split(r"^## ", texto, flags=re.M):
        bloque = bloque.strip()
        if not bloque:
            continue
        titulo, _, cuerpo = bloque.partition("\n")
        cuerpo = cuerpo.strip()
        if len(cuerpo) <= MAX_CARACTERES:
            salida.append((titulo.strip(), cuerpo))
            continue
        oraciones = re.split(r"(?<=[.;])\s+", cuerpo)
        actual = []
        for o in oraciones:
            if sum(len(x) for x in actual) + len(o) > MAX_CARACTERES and actual:
                salida.append((titulo.strip(), " ".join(actual)))
                actual = actual[-1:]          # solapamiento
            actual.append(o)
        if actual:
            salida.append((titulo.strip(), " ".join(actual)))
    return salida


async def main():
    t0 = time.perf_counter()
    print("› Creando esquema…")
    db.ejecutar((config.RAIZ / "sql" / "schema.sql").read_text(encoding="utf-8"))
    db.ejecutar((config.RAIZ / "sql" / "seed.sql").read_text(encoding="utf-8"))

    print("› Embeddings de las áreas jurídicas…")
    areas = db.consultar("SELECT slug, nombre, descripcion FROM areas")
    vecs = await llm.embeber([f"{a['nombre']}: {a['descripcion']}" for a in areas], tipo="documento",
                             titulo="área jurídica")
    for a, v in zip(areas, vecs):
        db.ejecutar("UPDATE areas SET embedding=%s WHERE slug=%s", (np.array(v, dtype=np.float32), a["slug"]))

    db.ejecutar("TRUNCATE fragmentos, documentos RESTART IDENTITY CASCADE")
    total = 0
    for ruta in sorted((config.RAIZ / "conocimiento").glob("*.md")):
        meta, texto = leer(ruta)
        doc = db.uno("INSERT INTO documentos (slug, titulo, fuente, area, url) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                     (meta["slug"], meta["titulo"], meta["fuente"], meta["area"], meta.get("url")))
        trozos = fragmentar(texto)
        # cada fragmento lleva su contexto (documento + sección) para mejorar la búsqueda
        entradas = [f"{seccion}. {cuerpo}" for seccion, cuerpo in trozos]
        vecs = await llm.embeber(entradas, tipo="documento", titulo=meta["titulo"])
        with db.conexion() as conn:
            for i, ((seccion, cuerpo), v) in enumerate(zip(trozos, vecs)):
                conn.execute("INSERT INTO fragmentos (documento_id, orden, seccion, contenido, tokens, embedding) "
                             "VALUES (%s,%s,%s,%s,%s,%s)",
                             (doc["id"], i, seccion, cuerpo, len(cuerpo.split()), np.array(v, dtype=np.float32)))
        total += len(trozos)
        print(f"  ✓ {meta['titulo']:<55} {len(trozos):>2} fragmentos")
    print(f"\nListo: {total} fragmentos con vectores de {len(vecs[0])} dimensiones "
          f"en {time.perf_counter() - t0:.1f} s")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except llm.ErrorOllama as e:
        print(f"\n✗ {e}")
        sys.exit(1)
    finally:
        db.cerrar()
