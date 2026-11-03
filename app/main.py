"""AMPARO · API del agente de orientación jurídica básica.

Flujo de una consulta (arquitectura sugerida por el curso):
  audio → STT → embedding (EmbeddingGemma) → PostgreSQL/pgvector → LLM → respuesta → TTS
"""
import asyncio
import json
import time
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, evaluacion, llm, orientacion, rag, voz

app = FastAPI(title="Amparo · Orientación jurídica básica")
WEB = config.RAIZ / "web"


# ---------------------------------------------------------------------------
# Estado del sistema
# ---------------------------------------------------------------------------
@app.get("/api/estado")
async def estado():
    info = {"llm": await llm.estado(), "stt": voz.stt_disponible(), "tts": voz.tts_disponible(),
            "whisper": config.WHISPER_MODELO, "db": False, "fragmentos": 0}
    try:
        fila = db.uno("SELECT (SELECT count(*) FROM fragmentos) AS f, (SELECT count(*) FROM documentos) AS d")
        info.update(db=True, fragmentos=fila["f"], documentos=fila["d"])
    except Exception as e:  # noqa: BLE001
        info["db_error"] = str(e)[:200]
    return info


# ---------------------------------------------------------------------------
# Conversaciones (datos transaccionales)
# ---------------------------------------------------------------------------
@app.get("/api/conversaciones")
def listar_conversaciones():
    filas = db.consultar(
        "SELECT c.id, c.titulo, c.urgencia, c.actualizada, a.nombre AS area, a.color, a.simbolo, "
        "(SELECT count(*) FROM mensajes m WHERE m.conversacion_id=c.id) AS mensajes "
        "FROM conversaciones c LEFT JOIN areas a ON a.slug=c.area ORDER BY c.actualizada DESC LIMIT 50")
    for f in filas:
        f["id"] = str(f["id"])
        f["actualizada"] = f["actualizada"].isoformat()
    return filas


@app.get("/api/conversaciones/{cid}")
def ver_conversacion(cid: uuid.UUID):
    msgs = db.consultar("SELECT id, rol, contenido, canal, fuentes, expediente, metricas, creado "
                        "FROM mensajes WHERE conversacion_id=%s ORDER BY creado", (cid,))
    for m in msgs:
        m["creado"] = m["creado"].isoformat()
    return msgs


@app.delete("/api/conversaciones/{cid}")
def borrar_conversacion(cid: uuid.UUID):
    db.ejecutar("DELETE FROM conversaciones WHERE id=%s", (cid,))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Consulta principal con streaming (Server-Sent Events)
# ---------------------------------------------------------------------------
class Consulta(BaseModel):
    texto: str
    conversacion_id: str | None = None
    modo: str = "sencillo"
    canal: str = "texto"
    ms_stt: int | None = None


def _evento(tipo: str, datos) -> bytes:
    return f"event: {tipo}\ndata: {json.dumps(datos, ensure_ascii=False, default=str)}\n\n".encode()


@app.post("/api/consulta")
async def consulta(c: Consulta):
    texto = c.texto.strip()
    if not texto:
        raise HTTPException(400, "La consulta está vacía")

    async def flujo():
        metricas = {"stt": c.ms_stt}
        t_total = time.perf_counter()
        cid = c.conversacion_id
        if cid:
            conv = db.uno("SELECT id, area FROM conversaciones WHERE id=%s", (cid,))
            if not conv:
                cid = None
        if not cid:
            conv = db.uno("INSERT INTO conversaciones (titulo) VALUES (%s) RETURNING id, area", (texto[:80],))
            cid = str(conv["id"])
        yield _evento("conversacion", {"id": cid})
        historial = db.consultar("SELECT rol, contenido FROM mensajes WHERE conversacion_id=%s "
                                 "ORDER BY creado DESC LIMIT 6", (cid,))[::-1]

        # 0) Seguridad
        emergencia = orientacion.detectar_emergencia(texto)
        if emergencia:
            yield _evento("emergencia", emergencia)

        # 1) Embedding de la consulta (con contexto si es una pregunta de seguimiento corta)
        yield _evento("etapa", {"etapa": "embedding", "estado": "inicio"})
        previas = [m["contenido"] for m in historial if m["rol"] == "usuario"]
        texto_busqueda = (previas[-1] + " " + texto) if previas and len(texto.split()) < 12 else texto
        t = time.perf_counter()
        try:
            vector = (await llm.embeber([texto_busqueda]))[0]
        except Exception as e:  # noqa: BLE001
            yield _evento("error", {"mensaje": f"No pude generar el embedding. ¿Está Ollama encendido con '{config.EMBED_MODELO}'? ({e})"})
            return
        metricas["embedding"] = round((time.perf_counter() - t) * 1000)
        yield _evento("etapa", {"etapa": "embedding", "estado": "fin", "ms": metricas["embedding"], "dim": len(vector)})

        # 2) Recuperación híbrida en PostgreSQL + pgvector
        yield _evento("etapa", {"etapa": "pgvector", "estado": "inicio"})
        t = time.perf_counter()
        fragmentos = rag.buscar(vector, texto_busqueda)
        sim_areas = rag.similitud_areas(vector)
        metricas["pgvector"] = round((time.perf_counter() - t) * 1000)
        utiles = [f for f in fragmentos if f["similitud"] >= config.RAG_UMBRAL]
        if len(utiles) < 3:                      # siempre al menos 3 fuentes de apoyo
            utiles = fragmentos[:3]
        yield _evento("etapa", {"etapa": "pgvector", "estado": "fin", "ms": metricas["pgvector"], "k": len(utiles)})
        yield _evento("fuentes", utiles)

        # 3) Expediente: área, urgencia, ruta y entidades
        clasif = orientacion.clasificar_area(sim_areas, utiles, conv.get("area"))
        area = clasif["principal"]
        if emergencia and emergencia["tipo"] in ("violencia", "menores"):
            forzada = next((a for a in sim_areas if a["slug"] == "violencia"), None)
            if forzada:   # la seguridad prima sobre la similitud semántica
                area = {"slug": "violencia", "nombre": forzada["nombre"], "color": forzada["color"],
                        "simbolo": forzada["simbolo"], "probabilidad": 1.0}
        urgencia = orientacion.evaluar_urgencia(" ".join(previas[-2:] + [texto]), emergencia)
        ruta, entidades = orientacion.ruta_y_entidades(area["slug"]) if area else ([], [])
        expediente = {"area": area, "distribucion": clasif["distribucion"], "urgencia": urgencia,
                      "ruta": ruta, "entidades": entidades}
        yield _evento("expediente", expediente)

        # 4) Generación con el LLM (streaming)
        yield _evento("etapa", {"etapa": "llm", "estado": "inicio", "modelo": config.LLM_MODELO})
        mensajes = orientacion.construir_mensajes(texto, utiles, historial, area, c.modo)
        t = time.perf_counter()
        primero, partes = None, []
        try:
            async for trozo in llm.chat_stream(mensajes):
                if primero is None:
                    primero = round((time.perf_counter() - t) * 1000)
                partes.append(trozo)
                yield _evento("token", trozo)
        except Exception as e:  # noqa: BLE001
            yield _evento("error", {"mensaje": f"El modelo '{config.LLM_MODELO}' no respondió: {e}"})
            return
        respuesta = "".join(partes).strip()
        metricas["llm"] = round((time.perf_counter() - t) * 1000)
        metricas["primer_token"] = primero
        metricas["tokens_aprox"] = len(partes)
        yield _evento("etapa", {"etapa": "llm", "estado": "fin", "ms": metricas["llm"]})

        # 5) Persistencia y trazabilidad
        metricas["total"] = round((time.perf_counter() - t_total) * 1000)
        fuentes_min = [{k: f[k] for k in ("id", "slug", "titulo", "seccion", "fuente", "similitud", "contenido")} for f in utiles]
        db.ejecutar("INSERT INTO mensajes (conversacion_id, rol, contenido, canal) VALUES (%s,'usuario',%s,%s)",
                    (cid, texto, c.canal))
        fila = db.uno("INSERT INTO mensajes (conversacion_id, rol, contenido, fuentes, expediente, metricas) "
                      "VALUES (%s,'agente',%s,%s,%s,%s) RETURNING id",
                      (cid, respuesta, json.dumps(fuentes_min), json.dumps(expediente, default=str),
                       json.dumps(metricas)))
        db.ejecutar("UPDATE conversaciones SET area=%s, urgencia=%s, actualizada=now() WHERE id=%s",
                    (area["slug"] if area else None, urgencia["nivel"], cid))
        yield _evento("fin", {"mensaje_id": fila["id"], "metricas": metricas})

    return StreamingResponse(flujo(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Voz
# ---------------------------------------------------------------------------
@app.post("/api/stt")
async def stt(audio: UploadFile = File(...)):
    if not voz.stt_disponible():
        raise HTTPException(501, "faster-whisper no está instalado")
    datos = await audio.read()
    return await asyncio.to_thread(voz.transcribir, datos)


class TextoVoz(BaseModel):
    texto: str


@app.post("/api/tts")
async def tts(t: TextoVoz):
    if not voz.tts_disponible():
        return JSONResponse({"detalle": "Piper no disponible; use la voz del navegador"}, status_code=501)
    inicio = time.perf_counter()
    wav = await asyncio.to_thread(voz.sintetizar, t.texto[:2500])
    return Response(wav, media_type="audio/wav",
                    headers={"X-TTS-ms": str(round((time.perf_counter() - inicio) * 1000))})


# ---------------------------------------------------------------------------
# Catálogos, documentos y evaluación
# ---------------------------------------------------------------------------
@app.get("/api/areas")
def areas():
    return db.consultar("SELECT slug, nombre, descripcion, color, simbolo FROM areas ORDER BY nombre")


@app.get("/api/entidades")
def entidades(area: str | None = None):
    if area:
        return db.consultar("SELECT * FROM entidades WHERE %s = ANY(areas) ORDER BY municipio, nombre", (area,))
    return db.consultar("SELECT * FROM entidades ORDER BY (municipio='Nacional'), municipio, nombre")


@app.get("/api/documentos-fuente")
def documentos_fuente():
    return db.consultar("SELECT d.slug, d.titulo, d.fuente, d.area, d.url, count(f.id) AS fragmentos "
                        "FROM documentos d LEFT JOIN fragmentos f ON f.documento_id=d.id GROUP BY d.id ORDER BY d.id")


class Redaccion(BaseModel):
    tipo: str
    hechos: str
    campos: dict = {}
    conversacion_id: str | None = None


@app.post("/api/redactar")
async def redactar(r: Redaccion):
    mensajes = [{"role": "system", "content": orientacion.REDACCION.format(tipo=r.tipo)},
                {"role": "user", "content": r.hechos}]
    try:
        texto = await llm.completar(mensajes)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"El modelo no respondió: {e}") from e
    cid = r.conversacion_id if r.conversacion_id and db.uno(
        "SELECT 1 FROM conversaciones WHERE id=%s", (r.conversacion_id,)) else None
    db.ejecutar("INSERT INTO documentos_generados (conversacion_id, tipo, campos) VALUES (%s,%s,%s)",
                (cid, r.tipo, json.dumps(r.campos | {"hechos": r.hechos}, ensure_ascii=False)))
    return {"hechos": texto.strip()}


@app.get("/api/metricas")
def metricas():
    por_area = db.consultar("SELECT a.nombre, a.color, a.simbolo, count(c.id) AS n FROM areas a "
                            "LEFT JOIN conversaciones c ON c.area=a.slug GROUP BY a.slug ORDER BY n DESC, a.nombre")
    lat = db.uno("SELECT count(*) AS respuestas, "
                 "round(avg((metricas->>'embedding')::numeric)) AS embedding, "
                 "round(avg((metricas->>'pgvector')::numeric)) AS pgvector, "
                 "round(avg((metricas->>'primer_token')::numeric)) AS primer_token, "
                 "round(avg((metricas->>'llm')::numeric)) AS llm, "
                 "round(avg((metricas->>'stt')::numeric)) AS stt "
                 "FROM mensajes WHERE rol='agente'")
    canales = db.consultar("SELECT canal, count(*) AS n FROM mensajes WHERE rol='usuario' GROUP BY canal")
    docs = db.uno("SELECT count(*) AS n FROM documentos_generados")
    return {"por_area": por_area, "latencias": lat, "canales": canales, "documentos_generados": docs["n"]}


@app.get("/api/evaluacion")
def ver_evaluacion():
    return evaluacion.ultima() or {}


@app.post("/api/evaluacion")
async def correr_evaluacion(con_llm: bool = False):
    return await evaluacion.ejecutar(con_llm=con_llm)


# ---------------------------------------------------------------------------
# Interfaz web
# ---------------------------------------------------------------------------
@app.get("/")
def inicio():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
