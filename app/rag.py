"""Recuperación híbrida: similitud vectorial (pgvector, HNSW coseno) +
búsqueda léxica en español (tsvector), fusionadas con Reciprocal Rank Fusion."""
import numpy as np

from . import config, db

SQL_HIBRIDO = """
WITH q AS (
    SELECT %(vec)s::vector AS v,
           to_tsquery('spanish', coalesce(nullif(array_to_string(
               tsvector_to_array(to_tsvector('spanish', %(texto)s)), ' | '), ''), 'xyzvacio')) AS t
),
semantico AS (
    SELECT f.id, 1 - (f.embedding <=> q.v) AS similitud,
           row_number() OVER (ORDER BY f.embedding <=> q.v) AS rango
    FROM fragmentos f, q
    ORDER BY f.embedding <=> q.v
    LIMIT 30
),
lexico AS (
    SELECT f.id, row_number() OVER (ORDER BY ts_rank_cd(f.tsv, q.t) DESC) AS rango
    FROM fragmentos f, q
    WHERE f.tsv @@ q.t
    ORDER BY ts_rank_cd(f.tsv, q.t) DESC
    LIMIT 30
),
fusion AS (
    SELECT coalesce(s.id, l.id) AS id,
           coalesce(1.0 / (60 + s.rango), 0) + coalesce(1.0 / (60 + l.rango), 0) AS rrf,
           s.rango AS rango_sem, l.rango AS rango_lex
    FROM semantico s FULL OUTER JOIN lexico l ON s.id = l.id
)
SELECT f.id, f.seccion, f.contenido, d.slug, d.titulo, d.fuente, d.area, d.url,
       1 - (f.embedding <=> (SELECT v FROM q)) AS similitud,
       fu.rrf, fu.rango_sem, fu.rango_lex
FROM fusion fu
JOIN fragmentos f ON f.id = fu.id
JOIN documentos d ON d.id = f.documento_id
ORDER BY fu.rrf DESC
LIMIT %(k)s
"""


def buscar(vector: list[float], texto: str, k: int | None = None) -> list[dict]:
    filas = db.consultar(SQL_HIBRIDO, {"vec": np.array(vector, dtype=np.float32),
                                       "texto": texto, "k": k or config.RAG_K})
    for f in filas:
        f["similitud"] = round(float(f["similitud"]), 4)
        f["rrf"] = round(float(f["rrf"]), 5)
    return filas


def similitud_areas(vector: list[float]) -> list[dict]:
    return db.consultar(
        "SELECT slug, nombre, color, simbolo, 1 - (embedding <=> %s) AS similitud "
        "FROM areas WHERE embedding IS NOT NULL ORDER BY similitud DESC",
        (np.array(vector, dtype=np.float32),))
