"""Evaluación del agente con casos de prueba concretos (eval/casos.json).

Métricas de recuperación y clasificación (rápidas, sin LLM):
  - Exactitud del área jurídica detectada
  - Hit@3 / Hit@5: ¿aparece el documento esperado entre los primeros k?
  - MRR: rango recíproco medio del documento esperado
  - Detección correcta de emergencias y de pedidos fuera de los límites del agente
Opcionalmente (con_llm=True) mide cobertura de palabras clave en la respuesta.
"""
import json
import time

from . import config, db, llm, orientacion, rag

CASOS = config.RAIZ / "eval" / "casos.json"


async def ejecutar(con_llm: bool = False) -> dict:
    casos = json.loads(CASOS.read_text(encoding="utf-8"))
    resultados = []
    for c in casos:
        t0 = time.perf_counter()
        vec = (await llm.embeber([c["pregunta"]]))[0]
        frags = rag.buscar(vec, c["pregunta"], k=5)
        area = orientacion.clasificar_area(rag.similitud_areas(vec), frags)["principal"]
        emerg = orientacion.detectar_emergencia(c["pregunta"]) is not None
        limite = orientacion.detectar_limite(c["pregunta"]) is not None
        slugs = [f["slug"] for f in frags]
        rango = slugs.index(c["documento"]) + 1 if c["documento"] in slugs else None
        r = {
            "pregunta": c["pregunta"], "area_esperada": c["area"], "area_obtenida": area["slug"] if area else None,
            "documento": c["documento"], "rango": rango, "top": slugs[:3],
            "emergencia_esperada": c.get("emergencia", False), "emergencia": emerg,
            "limite_esperado": c.get("limite", False), "limite": limite,
            "ms": round((time.perf_counter() - t0) * 1000),
        }
        if con_llm:
            msgs = orientacion.construir_mensajes(c["pregunta"], frags, [], area, "sencillo",
                                                  orientacion.detectar_limite(c["pregunta"]))
            respuesta = orientacion.normalizar(await llm.completar(msgs))
            claves = c.get("claves", [])
            r["cobertura"] = round(sum(orientacion.normalizar(k) in respuesta for k in claves) / max(len(claves), 1), 2)
        resultados.append(r)

    n = len(resultados)
    resumen = {
        "casos": n,
        "exactitud_area": round(sum(r["area_esperada"] == r["area_obtenida"] for r in resultados) / n, 3),
        "hit_3": round(sum(1 for r in resultados if r["rango"] and r["rango"] <= 3) / n, 3),
        "hit_5": round(sum(1 for r in resultados if r["rango"]) / n, 3),
        "mrr": round(sum(1 / r["rango"] for r in resultados if r["rango"]) / n, 3),
        "emergencias": round(sum(r["emergencia"] == r["emergencia_esperada"] for r in resultados) / n, 3),
        "limites": round(sum(r["limite"] == r["limite_esperado"] for r in resultados) / n, 3),
        "latencia_ms": round(sum(r["ms"] for r in resultados) / n),
        "modelo_embeddings": config.EMBED_MODELO,
    }
    if con_llm:
        resumen["cobertura_respuesta"] = round(sum(r["cobertura"] for r in resultados) / n, 3)
        resumen["modelo_llm"] = config.LLM_MODELO
    db.ejecutar("INSERT INTO evaluaciones (resumen, casos) VALUES (%s, %s)",
                (json.dumps(resumen), json.dumps(resultados, ensure_ascii=False)))
    return {"resumen": resumen, "casos": resultados}


def ultima() -> dict | None:
    fila = db.uno("SELECT ejecutada, resumen, casos FROM evaluaciones ORDER BY id DESC LIMIT 1")
    if fila:
        fila["ejecutada"] = fila["ejecutada"].isoformat()
    return fila
