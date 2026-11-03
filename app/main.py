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
ESTADOS = ("abierto", "orientado", "remitido", "en_tramite", "cerrado")


@app.on_event("startup")
def migrar():
    """Aplica el esquema (idempotente) para que las tablas nuevas existan sin reingestar."""
    try:
        db.ejecutar((config.RAIZ / "sql" / "schema.sql").read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print("Aviso: no se pudo aplicar el esquema:", e)


def _cambiar_estado(cid, estado: str, nota: str | None = None) -> None:
    db.ejecutar("UPDATE conversaciones SET estado=%s, actualizada=now() WHERE id=%s", (estado, cid))
    db.ejecutar("INSERT INTO historial_estados (conversacion_id, estado, nota) VALUES (%s,%s,%s)", (cid, estado, nota))


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
        "SELECT c.id, c.titulo, c.urgencia, c.estado, c.notas, c.actualizada, c.area AS area_slug, "
        "a.nombre AS area, a.color, a.simbolo, p.id AS consultante_id, p.nombre AS consultante, "
        "(SELECT count(*) FROM mensajes m WHERE m.conversacion_id=c.id) AS mensajes, "
        "(SELECT count(*) FROM documentos_generados d WHERE d.conversacion_id=c.id) AS documentos, "
        "(SELECT min(ci.fecha::text || ' ' || to_char(ci.hora,'HH24:MI')) FROM citas_consultorio ci "
        "  WHERE ci.conversacion_id=c.id AND ci.estado IN ('solicitada','confirmada')) AS proxima_cita "
        "FROM conversaciones c LEFT JOIN areas a ON a.slug=c.area LEFT JOIN consultantes p ON p.id=c.consultante_id "
        "ORDER BY c.actualizada DESC LIMIT 100")
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
    consultante_id: int | None = None


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
            conv = db.uno("INSERT INTO conversaciones (titulo, consultante_id) VALUES (%s, %s) RETURNING id, area",
                          (texto[:80], c.consultante_id))
            cid = str(conv["id"])
            _cambiar_estado(cid, "abierto", "Caso creado")
        yield _evento("conversacion", {"id": cid})
        historial = db.consultar("SELECT rol, contenido FROM mensajes WHERE conversacion_id=%s "
                                 "ORDER BY creado DESC LIMIT 6", (cid,))[::-1]

        # 0) Seguridad
        emergencia = orientacion.detectar_emergencia(texto)
        if emergencia:
            yield _evento("emergencia", emergencia)
        limite = orientacion.detectar_limite(texto)
        if limite:
            yield _evento("limite", limite)

        # 1) Embedding de la consulta (con contexto si es una pregunta de seguimiento corta)
        yield _evento("etapa", {"etapa": "embedding", "estado": "inicio"})
        previas = [m["contenido"] for m in historial if m["rol"] == "usuario"]
        texto_busqueda = (previas[-1] + " " + texto) if previas and len(texto.split()) < 12 else texto
        t = time.perf_counter()
        try:
            vector = (await llm.embeber([texto_busqueda]))[0]
        except Exception as e:  # noqa: BLE001
            mensaje = str(e) if isinstance(e, llm.ErrorOllama) else \
                f"No pude generar el embedding. ¿Está Ollama encendido con '{config.EMBED_MODELO}'? ({e})"
            yield _evento("error", {"mensaje": mensaje})
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
        mensajes = orientacion.construir_mensajes(texto, utiles, historial, area, c.modo, limite)
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

        # Cierre obligatorio: límites del agente y remisión al consultorio jurídico
        con_citas = db.consultar("SELECT id, nombre, tipo, horario FROM entidades WHERE atiende_citas "
                                 "ORDER BY (nombre ILIKE 'Consultorio%%') DESC, nombre")
        expediente["remision"] = orientacion.remision(con_citas, limite)
        yield _evento("remision", expediente["remision"])

        # 5) Persistencia y trazabilidad
        metricas["total"] = round((time.perf_counter() - t_total) * 1000)
        fuentes_min = [{k: f[k] for k in ("id", "slug", "titulo", "seccion", "fuente", "similitud", "contenido")} for f in utiles]
        db.ejecutar("INSERT INTO mensajes (conversacion_id, rol, contenido, canal) VALUES (%s,'usuario',%s,%s)",
                    (cid, texto, c.canal))
        fila = db.uno("INSERT INTO mensajes (conversacion_id, rol, contenido, fuentes, expediente, metricas) "
                      "VALUES (%s,'agente',%s,%s,%s,%s) RETURNING id",
                      (cid, respuesta, json.dumps(fuentes_min), json.dumps(expediente, default=str),
                       json.dumps(metricas)))
        estado = db.uno("UPDATE conversaciones SET area=%s, urgencia=%s, actualizada=now() WHERE id=%s RETURNING estado",
                        (area["slug"] if area else None, urgencia["nivel"], cid))
        if estado and estado["estado"] == "abierto":
            _cambiar_estado(cid, "orientado", "Primera orientación entregada por Amparo")
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
    try:
        return await asyncio.to_thread(voz.transcribir, datos)
    except Exception as e:  # noqa: BLE001
        print("Error en STT:", repr(e))
        raise HTTPException(500, f"No se pudo transcribir el audio: {e}") from e


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
    db.ejecutar("INSERT INTO documentos_generados (conversacion_id, tipo, campos, origen) VALUES (%s,%s,%s,'redaccion_ia')",
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
    por_estado = db.consultar("SELECT estado, count(*) AS n FROM conversaciones GROUP BY estado")
    citas = db.consultar("SELECT estado, count(*) AS n FROM citas_consultorio GROUP BY estado")
    consultantes = db.uno("SELECT count(*) AS n FROM consultantes")
    return {"por_area": por_area, "latencias": lat, "canales": canales, "documentos_generados": docs["n"],
            "por_estado": por_estado, "citas": citas, "consultantes": consultantes["n"]}


@app.get("/api/evaluacion")
def ver_evaluacion():
    return evaluacion.ultima() or {}


@app.post("/api/evaluacion")
async def correr_evaluacion(con_llm: bool = False):
    return await evaluacion.ejecutar(con_llm=con_llm)



# ---------------------------------------------------------------------------
# Consultantes, casos, citas y documentos (gestión del consultorio)
# ---------------------------------------------------------------------------
class Consultante(BaseModel):
    nombre: str
    documento: str | None = None
    telefono: str | None = None
    correo: str | None = None
    municipio: str | None = "Mocoa"
    zona: str | None = None
    consentimiento: bool = False
    conversacion_id: str | None = None


def _guardar_consultante(p: Consultante) -> dict:
    if not p.consentimiento:
        raise HTTPException(400, "Se requiere la autorización de tratamiento de datos (Ley 1581 de 2012)")
    if not p.nombre.strip():
        raise HTTPException(400, "El nombre es obligatorio")
    zona = p.zona if p.zona in ("urbana", "rural") else None
    datos = (p.nombre.strip(), (p.documento or "").strip() or None, p.telefono, p.correo, p.municipio, zona)
    fila = None
    if datos[1]:
        fila = db.uno("UPDATE consultantes SET nombre=%s, telefono=%s, correo=%s, municipio=%s, zona=%s, consentimiento=TRUE "
                      "WHERE documento=%s RETURNING *", (datos[0], datos[2], datos[3], datos[4], datos[5], datos[1]))
    if not fila:
        fila = db.uno("INSERT INTO consultantes (nombre, documento, telefono, correo, municipio, zona, consentimiento) "
                      "VALUES (%s,%s,%s,%s,%s,%s,TRUE) RETURNING *", datos)
    if p.conversacion_id:
        db.ejecutar("UPDATE conversaciones SET consultante_id=%s WHERE id=%s", (fila["id"], p.conversacion_id))
    fila["creado"] = fila["creado"].isoformat()
    return fila


@app.post("/api/consultantes")
def crear_consultante(p: Consultante):
    return _guardar_consultante(p)


@app.get("/api/consultantes/{pid}")
def ver_consultante(pid: int):
    fila = db.uno("SELECT * FROM consultantes WHERE id=%s", (pid,))
    if not fila:
        raise HTTPException(404, "Consultante no encontrado")
    fila["creado"] = fila["creado"].isoformat()
    return fila


class CambioCaso(BaseModel):
    estado: str | None = None
    notas: str | None = None


@app.patch("/api/casos/{cid}")
def actualizar_caso(cid: uuid.UUID, c: CambioCaso):
    if c.estado:
        if c.estado not in ESTADOS:
            raise HTTPException(400, f"Estado inválido. Use: {', '.join(ESTADOS)}")
        _cambiar_estado(cid, c.estado, c.notas)
    elif c.notas is not None:
        db.ejecutar("UPDATE conversaciones SET notas=%s, actualizada=now() WHERE id=%s", (c.notas, cid))
    return {"ok": True}


@app.get("/api/casos/{cid}")
def ver_caso(cid: uuid.UUID):
    caso = db.uno("SELECT c.id, c.estado, c.notas, c.area, p.id AS consultante_id, p.nombre, p.documento, p.telefono, "
                  "p.correo, p.municipio, p.zona FROM conversaciones c LEFT JOIN consultantes p ON p.id=c.consultante_id "
                  "WHERE c.id=%s", (cid,))
    if not caso:
        raise HTTPException(404, "Caso no encontrado")
    caso["id"] = str(caso["id"])
    citas = db.consultar("SELECT ci.id, ci.fecha, ci.hora, ci.modalidad, ci.estado, e.nombre AS entidad "
                         "FROM citas_consultorio ci JOIN entidades e ON e.id=ci.entidad_id "
                         "WHERE ci.conversacion_id=%s ORDER BY ci.fecha, ci.hora", (cid,))
    caso["citas"] = [{**c, "fecha": c["fecha"].isoformat(), "hora": c["hora"].strftime("%H:%M")} for c in citas]
    return caso


@app.get("/api/casos/{cid}/historial")
def historial_caso(cid: uuid.UUID):
    filas = db.consultar("SELECT estado, nota, creado FROM historial_estados WHERE conversacion_id=%s ORDER BY creado", (cid,))
    for f in filas:
        f["creado"] = f["creado"].isoformat()
    return filas


HORAS = ["08:00", "09:00", "10:00", "11:00", "14:00", "15:00", "16:00"]


@app.get("/api/citas/disponibilidad")
def disponibilidad(entidad_id: int, fecha: str):
    ocupadas = {f["h"] for f in db.consultar(
        "SELECT to_char(hora,'HH24:MI') AS h FROM citas_consultorio WHERE entidad_id=%s AND fecha=%s AND estado<>'cancelada'",
        (entidad_id, fecha))}
    return [{"hora": h, "libre": h not in ocupadas} for h in HORAS]


class Cita(BaseModel):
    entidad_id: int
    fecha: str
    hora: str
    modalidad: str = "presencial"
    motivo: str | None = None
    conversacion_id: str | None = None
    consultante_id: int | None = None
    consultante: Consultante | None = None


def _cita_json(f: dict) -> dict:
    f["fecha"] = f["fecha"].isoformat()
    f["hora"] = f["hora"].strftime("%H:%M")
    f["creado"] = f["creado"].isoformat()
    if f.get("conversacion_id"):
        f["conversacion_id"] = str(f["conversacion_id"])
    return f


@app.post("/api/citas")
def agendar_cita(c: Cita):
    pid = c.consultante_id
    if c.consultante:
        c.consultante.conversacion_id = c.conversacion_id
        pid = _guardar_consultante(c.consultante)["id"]
    if not pid:
        raise HTTPException(400, "Faltan los datos del consultante")
    if c.hora not in HORAS:
        raise HTTPException(400, "Horario no disponible")
    try:
        fila = db.uno("INSERT INTO citas_consultorio (conversacion_id, consultante_id, entidad_id, fecha, hora, modalidad, motivo) "
                      "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                      (c.conversacion_id, pid, c.entidad_id, c.fecha, c.hora, c.modalidad, c.motivo))
    except Exception as e:  # noqa: BLE001
        if "citas_horario_uq" in str(e):
            raise HTTPException(409, "Ese horario acaba de ser tomado. Elija otro.") from e
        raise
    if c.conversacion_id:
        _cambiar_estado(c.conversacion_id, "remitido", f"Cita agendada para el {c.fecha} a las {c.hora}")
    return _cita_json(fila) | {"entidad": db.uno("SELECT nombre, horario FROM entidades WHERE id=%s", (c.entidad_id,))}


@app.get("/api/citas")
def listar_citas():
    filas = db.consultar(
        "SELECT ci.*, e.nombre AS entidad, p.nombre AS consultante, p.telefono, c.titulo AS caso "
        "FROM citas_consultorio ci JOIN entidades e ON e.id=ci.entidad_id JOIN consultantes p ON p.id=ci.consultante_id "
        "LEFT JOIN conversaciones c ON c.id=ci.conversacion_id ORDER BY ci.fecha, ci.hora")
    return [_cita_json(f) for f in filas]


class EstadoCita(BaseModel):
    estado: str


@app.patch("/api/citas/{cita_id}")
def cambiar_cita(cita_id: int, e: EstadoCita):
    if e.estado not in ("solicitada", "confirmada", "atendida", "cancelada"):
        raise HTTPException(400, "Estado de cita inválido")
    fila = db.uno("UPDATE citas_consultorio SET estado=%s WHERE id=%s RETURNING conversacion_id", (e.estado, cita_id))
    if fila and fila["conversacion_id"] and e.estado == "atendida":
        _cambiar_estado(fila["conversacion_id"], "en_tramite", "El consultorio atendió la cita")
    return {"ok": True}


class DocumentoGenerado(BaseModel):
    tipo: str
    campos: dict = {}
    conversacion_id: str | None = None
    consultante_id: int | None = None


@app.post("/api/documentos")
def registrar_documento(d: DocumentoGenerado):
    cid = d.conversacion_id if d.conversacion_id and db.uno(
        "SELECT 1 FROM conversaciones WHERE id=%s", (d.conversacion_id,)) else None
    fila = db.uno("INSERT INTO documentos_generados (conversacion_id, consultante_id, tipo, campos, origen) "
                  "VALUES (%s,%s,%s,%s,'impresion') RETURNING id", (cid, d.consultante_id, d.tipo,
                                                                    json.dumps(d.campos, ensure_ascii=False)))
    return {"id": fila["id"]}

# ---------------------------------------------------------------------------
# Interfaz web
# ---------------------------------------------------------------------------
@app.get("/")
def inicio():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
