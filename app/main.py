"""AMPARO · API del agente de orientación jurídica básica.

Flujo de una consulta (arquitectura sugerida por el curso):
  audio → STT → embedding (EmbeddingGemma) → PostgreSQL/pgvector → LLM → respuesta → TTS
"""
import asyncio
import json
import re
import time
import uuid
from datetime import date

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agenda, config, db, evaluacion, llm, orientacion, personalidad, rag, voz

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
            "whisper": config.WHISPER_MODELO, "whisper_llamada": config.WHISPER_LLAMADA, "db": False, "fragmentos": 0}
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
        "SELECT c.id, c.titulo, c.urgencia, c.estado, c.notas, c.actualizada, c.creada, c.area AS area_slug, "
        "c.alias, c.bloqueada, c.motivo_cierre, c.advertencias, "
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
        f["creada"] = f["creada"].isoformat()
    return filas


@app.get("/api/conversaciones/{cid}")
def ver_conversacion(cid: uuid.UUID):
    msgs = db.consultar("SELECT id, rol, contenido, canal, fuentes, expediente, metricas, guion, tipo, creado "
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
    alias: str | None = None          # nombre o apodo con el que quiere que Amparo le llame
    voz: bool = True                  # si la interfaz va a hablar: genera la explicación hablada con el LLM


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
        alias = (c.alias or "").strip()[:40] or None
        conv = None
        if cid:
            conv = db.uno("SELECT id, area, alias, advertencias, bloqueada FROM conversaciones WHERE id=%s", (cid,))
            if not conv:
                cid = None
        if conv and conv["bloqueada"]:
            yield _evento("sesion_cerrada", {"motivo": "Esta charla se cerró. Para empezar de cero, recargue la página."})
            return
        if not cid:
            conv = db.uno("INSERT INTO conversaciones (titulo, consultante_id, alias) VALUES (%s, %s, %s) "
                          "RETURNING id, area, alias, advertencias, bloqueada", (texto[:80], c.consultante_id, alias))
            cid = str(conv["id"])
            _cambiar_estado(cid, "abierto", "Caso creado")
        elif alias and alias != conv["alias"]:
            db.ejecutar("UPDATE conversaciones SET alias=%s WHERE id=%s", (alias, cid))
        nombre = alias or conv["alias"]
        yield _evento("conversacion", {"id": cid})
        historial = db.consultar("SELECT rol, contenido FROM mensajes WHERE conversacion_id=%s "
                                 "ORDER BY creado DESC LIMIT 6", (cid,))[::-1]

        # 0) Seguridad
        emergencia = orientacion.detectar_emergencia(texto)
        if emergencia:
            yield _evento("emergencia", emergencia)

        # 0b) Personalidad: ofensas, preguntas sobre Amparo y temas no jurídicos (respuestas al instante, sin LLM)
        if not emergencia:
            tipo = None
            if personalidad.detectar_ofensa(texto):
                avisos = (conv["advertencias"] or 0) + 1
                db.ejecutar("UPDATE conversaciones SET advertencias=%s WHERE id=%s", (avisos, cid))
                tipo = "aviso" if avisos < 2 else "cierre"
            else:
                tipo = personalidad.detectar_identidad(texto) or ("fuera_tema" if personalidad.fuera_de_tema(texto) else None)
            if tipo:
                async for ev in _respuesta_fija(cid, texto, c.canal, tipo, nombre, metricas, t_total):
                    yield ev
                return

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
        mensajes = orientacion.construir_mensajes(texto, utiles, historial, area, c.modo, limite, nombre)
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

        # 4b) Explicación hablada: lo que Amparo DICE en voz, corto y con emoción (no lee el texto completo)
        yield _evento("etapa", {"etapa": "guion", "estado": "inicio"})
        t = time.perf_counter()
        guion, origen = None, "reglas"
        if c.voz and config.VOZ_GUION == "llm":
            try:
                crudo = await asyncio.wait_for(llm.completar(
                    personalidad.mensajes_guion(texto, respuesta, nombre, urgencia["nivel"]),
                    max_tokens=180, temperatura=0.6), timeout=60)
                guion = personalidad.parsear_guion(crudo)
                origen = "llm"
            except Exception as e:  # noqa: BLE001
                print("Aviso: no se pudo generar el guion hablado:", repr(e))
        if not guion or len(guion) < 2:
            guion, origen = personalidad.guion_por_reglas(respuesta, nombre, urgencia["nivel"]), "reglas"
        if emergencia:
            guion.insert(0, {"emocion": "seria", "texto": "Antes que nada: si está en peligro ahora, llame al uno, dos, tres."})
        metricas["guion"] = round((time.perf_counter() - t) * 1000)
        yield _evento("etapa", {"etapa": "guion", "estado": "fin", "ms": metricas["guion"]})
        yield _evento("guion", {"segmentos": guion, "origen": origen})

        # 5) Persistencia y trazabilidad
        metricas["total"] = round((time.perf_counter() - t_total) * 1000)
        fuentes_min = [{k: f[k] for k in ("id", "slug", "titulo", "seccion", "fuente", "similitud", "contenido")} for f in utiles]
        # Si la charla empezó con un saludo o una pregunta sobre Amparo, el título pasa a ser la primera consulta real
        db.ejecutar("UPDATE conversaciones SET titulo=%s WHERE id=%s AND NOT EXISTS "
                    "(SELECT 1 FROM mensajes WHERE conversacion_id=%s AND rol='agente' AND tipo='orientacion')", (texto[:80], cid, cid))
        db.ejecutar("INSERT INTO mensajes (conversacion_id, rol, contenido, canal) VALUES (%s,'usuario',%s,%s)",
                    (cid, texto, c.canal))
        fila = db.uno("INSERT INTO mensajes (conversacion_id, rol, contenido, fuentes, expediente, metricas, guion, tipo) "
                      "VALUES (%s,'agente',%s,%s,%s,%s,%s,'orientacion') RETURNING id",
                      (cid, respuesta, json.dumps(fuentes_min), json.dumps(expediente, default=str),
                       json.dumps(metricas), json.dumps(guion, ensure_ascii=False)))
        estado = db.uno("UPDATE conversaciones SET area=%s, urgencia=%s, actualizada=now() WHERE id=%s RETURNING estado",
                        (area["slug"] if area else None, urgencia["nivel"], cid))
        if estado and estado["estado"] == "abierto":
            _cambiar_estado(cid, "orientado", "Primera orientación entregada por Amparo")
        yield _evento("fin", {"mensaje_id": fila["id"], "metricas": metricas})

    return StreamingResponse(flujo(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _respuesta_fija(cid, texto, canal, tipo, nombre, metricas, t_total):
    """Respuestas de personalidad: quién es Amparo, saludos, temas no jurídicos, avisos y cierre de sesión."""
    r = personalidad.respuesta_fija(tipo, nombre)
    yield _evento("tipo_respuesta", {"tipo": tipo})
    for palabra in re.split(r"(?<=\s)", r["texto"]):          # efecto de escritura natural
        yield _evento("token", palabra)
        await asyncio.sleep(0.008)
    yield _evento("guion", {"segmentos": r["guion"], "origen": "personalidad"})
    metricas["total"] = round((time.perf_counter() - t_total) * 1000)
    db.ejecutar("INSERT INTO mensajes (conversacion_id, rol, contenido, canal) VALUES (%s,'usuario',%s,%s)", (cid, texto, canal))
    fila = db.uno("INSERT INTO mensajes (conversacion_id, rol, contenido, metricas, guion, tipo) "
                  "VALUES (%s,'agente',%s,%s,%s,%s) RETURNING id",
                  (cid, r["texto"], json.dumps(metricas), json.dumps(r["guion"], ensure_ascii=False), tipo))
    db.ejecutar("UPDATE conversaciones SET actualizada=now() WHERE id=%s", (cid,))
    if tipo == "cierre":
        db.ejecutar("UPDATE conversaciones SET bloqueada=TRUE, motivo_cierre=%s WHERE id=%s",
                    ("Lenguaje ofensivo repetido", cid))
        _cambiar_estado(cid, "cerrado", "Sesión cerrada por lenguaje ofensivo repetido")
        yield _evento("sesion_cerrada", {"motivo": "Para empezar de cero, recargue la página."})
    yield _evento("fin", {"mensaje_id": fila["id"], "metricas": metricas, "tipo": tipo})


# ---------------------------------------------------------------------------
# Llamada en vivo: turnos de voz con respuesta por frases (streaming)
# ---------------------------------------------------------------------------
class TurnoLlamada(BaseModel):
    texto: str
    conversacion_id: str | None = None
    alias: str | None = None
    ms_stt: int | None = None


def _contexto_agenda(cid: str, alias: str | None) -> agenda.Contexto:
    entidades_cita = db.consultar("SELECT id, nombre, horario FROM entidades WHERE atiende_citas "
                                  "ORDER BY (nombre ILIKE 'Consultorio%%') DESC, id")

    def crear(d: dict) -> dict:
        p = _guardar_consultante(Consultante(nombre=d["nombre"], documento=d["documento"], telefono=d["telefono"],
                                             consentimiento=True, conversacion_id=cid))
        try:
            fila = _insertar_cita(cid, p["id"], d["entidad_id"], d["fecha"], d["hora"], d["modalidad"],
                                  d["motivo"], origen="llamada")
        except HTTPException as e:
            if e.status_code == 409:
                raise agenda.HorarioOcupado() from e
            raise
        return fila | {"consultante": p["nombre"], "telefono": p["telefono"], "documento": p["documento"]}

    return agenda.Contexto(entidades=entidades_cita, horas_libres=horas_libres, crear=crear, alias=alias)


async def _turno_agenda(texto: str, cid: str, conv: dict, nombre: str | None, historial: list[dict], dichas: list[dict]):
    """Un paso de la agenda por voz: interpreta, valida contra la disponibilidad real y responde."""
    previas = [m["contenido"] for m in historial if m["rol"] == "usuario" and not agenda.quiere_agendar(m["contenido"])]
    motivo = " / ".join(previas[-2:]) or "Consulta hecha en la llamada en vivo"
    ctx = await asyncio.to_thread(_contexto_agenda, cid, nombre)
    if not ctx.entidades:
        frase = {"emocion": "calida", "texto": "Uy, por ahora no tengo entidades con agenda disponible. "
                                                "Puede usar el botón de agendar cita en la pantalla."}
        dichas.append(frase)
        yield _evento("frase", frase)
        return
    res = await asyncio.to_thread(agenda.procesar, texto, conv["agenda"], ctx, motivo)
    db.ejecutar("UPDATE conversaciones SET agenda=%s, actualizada=now() WHERE id=%s",
                (json.dumps(res.estado, ensure_ascii=False) if res.estado else None, cid))
    if res.estado:
        yield _evento("agenda", agenda.resumen_publico(res.estado))
    elif res.cancelada:
        yield _evento("agenda", None)
    if res.cita:
        yield _evento("cita", res.cita)
    for frase in res.frases:
        dichas.append(frase)
        yield _evento("frase", frase)


@app.post("/api/llamada")
async def llamada(c: TurnoLlamada):
    """Un turno de la llamada. Emite cada frase apenas está completa para que la voz empiece de inmediato.

    Si la persona interrumpe, el navegador corta esta petición: lo dicho hasta ahí queda guardado
    y marcado como interrumpido.
    """
    texto = c.texto.strip()
    if not texto:
        raise HTTPException(400, "El turno está vacío")
    alias = (c.alias or "").strip()[:40] or None

    async def flujo():
        t0 = time.perf_counter()
        metricas = {"stt": c.ms_stt}
        cid, conv = c.conversacion_id, None
        if cid:
            conv = db.uno("SELECT id, area, alias, advertencias, bloqueada, agenda FROM conversaciones WHERE id=%s", (cid,))
        if conv and conv["bloqueada"]:
            yield _evento("colgar", {"motivo": "Esta llamada se cerró. Recargue la página para empezar de nuevo."})
            return
        if not conv:
            conv = db.uno("INSERT INTO conversaciones (titulo, alias) VALUES (%s, %s) "
                          "RETURNING id, area, alias, advertencias, bloqueada, agenda", ("📞 " + texto[:76], alias))
            cid = str(conv["id"])
            _cambiar_estado(cid, "abierto", "Llamada en vivo iniciada")
        nombre = alias or conv["alias"]
        yield _evento("conversacion", {"id": cid})
        historial = db.consultar("SELECT rol, contenido FROM mensajes WHERE conversacion_id=%s "
                                 "ORDER BY creado DESC LIMIT 6", (cid,))[::-1]
        db.ejecutar("INSERT INTO mensajes (conversacion_id, rol, contenido, canal) VALUES (%s,'usuario',%s,'llamada')",
                    (cid, texto))

        dichas: list[dict] = []
        estado = {"tipo": "llamada", "fuentes": [], "completa": False}

        def guardar():
            if not dichas:
                return
            contenido = " ".join(f["texto"] for f in dichas) + ("" if estado["completa"] else " (interrumpida)")
            metricas["total"] = round((time.perf_counter() - t0) * 1000)
            db.ejecutar("INSERT INTO mensajes (conversacion_id, rol, contenido, canal, fuentes, metricas, guion, tipo) "
                        "VALUES (%s,'agente',%s,'llamada',%s,%s,%s,%s)",
                        (cid, contenido, json.dumps(estado["fuentes"], ensure_ascii=False), json.dumps(metricas),
                         json.dumps(dichas, ensure_ascii=False), estado["tipo"]))
            db.ejecutar("UPDATE conversaciones SET actualizada=now() WHERE id=%s", (cid,))

        try:
            # 0) Seguridad y personalidad (instantáneo)
            emergencia = orientacion.detectar_emergencia(texto)
            if emergencia:
                yield _evento("emergencia", emergencia)
                frase = {"emocion": "seria", "texto": "Antes que nada: si está en peligro ahora, llame al uno, dos, tres. "
                                                      "Hay ayuda gratuita las veinticuatro horas."}
                dichas.append(frase)
                yield _evento("frase", frase)
            else:
                tipo = None
                if personalidad.detectar_ofensa(texto):
                    avisos = (conv["advertencias"] or 0) + 1
                    db.ejecutar("UPDATE conversaciones SET advertencias=%s WHERE id=%s", (avisos, cid))
                    tipo = "aviso" if avisos < 2 else "cierre"
                else:
                    # La agenda por voz va antes que la orientación: si se está agendando, cada turno es un paso.
                    ultima = next((m["contenido"] for m in reversed(historial) if m["rol"] == "agente"), None)
                    if conv["agenda"] or agenda.quiere_agendar(texto) or agenda.acepta_oferta(texto, ultima):
                        estado["tipo"] = "agenda"
                        async for ev in _turno_agenda(texto, cid, conv, nombre, historial, dichas):
                            yield ev
                        estado["completa"] = True
                        yield _evento("fin", {"metricas": metricas, "tipo": "agenda"})
                        return
                    tipo = personalidad.detectar_identidad(texto) or ("fuera_tema" if personalidad.fuera_de_tema(texto) else None)
                if tipo:
                    estado["tipo"] = tipo
                    for frase in personalidad.respuesta_fija(tipo, nombre)["guion"]:
                        dichas.append(frase)
                        yield _evento("frase", frase)
                    estado["completa"] = True
                    if tipo == "cierre":
                        db.ejecutar("UPDATE conversaciones SET bloqueada=TRUE, motivo_cierre=%s WHERE id=%s",
                                    ("Lenguaje ofensivo repetido", cid))
                        _cambiar_estado(cid, "cerrado", "Llamada cerrada por lenguaje ofensivo repetido")
                        yield _evento("colgar", {"motivo": "Amparo cerró la llamada. Para empezar de cero, recargue la página."})
                    yield _evento("fin", {"metricas": metricas, "tipo": tipo})
                    return

            # 1) Recuperación breve (3 fragmentos) para responder con fundamento
            previas = [m["contenido"] for m in historial if m["rol"] == "usuario"]
            busqueda = (previas[-1] + " " + texto) if previas and len(texto.split()) < 10 else texto
            t = time.perf_counter()
            try:
                vector = (await llm.embeber([busqueda]))[0]
            except Exception as e:  # noqa: BLE001
                yield _evento("error", {"mensaje": str(e) if isinstance(e, llm.ErrorOllama) else f"Sin embeddings: {e}"})
                return
            fragmentos = rag.buscar(vector, busqueda, k=3)
            metricas["recuperacion"] = round((time.perf_counter() - t) * 1000)
            estado["fuentes"] = [{k: f[k] for k in ("slug", "titulo", "seccion", "fuente", "similitud")} for f in fragmentos]
            yield _evento("fuentes", estado["fuentes"])
            clasif = orientacion.clasificar_area(rag.similitud_areas(vector), fragmentos, conv.get("area"))
            if clasif["principal"] and not emergencia:
                db.ejecutar("UPDATE conversaciones SET area=%s WHERE id=%s", (clasif["principal"]["slug"], cid))
            elif emergencia:
                db.ejecutar("UPDATE conversaciones SET area='violencia', urgencia='critica' WHERE id=%s", (cid,))

            # 2) El LLM responde y cada frase sale apenas se completa
            t = time.perf_counter()
            cortador = personalidad.Frases()
            try:
                async for token in llm.chat_stream(personalidad.mensajes_llamada(texto, fragmentos, historial, nombre),
                                                   max_tokens=160, temperatura=0.5):
                    for frase in cortador.agregar(token):
                        metricas.setdefault("primera_frase", round((time.perf_counter() - t) * 1000))
                        dichas.append(frase)
                        yield _evento("frase", frase)
                for frase in cortador.terminar():
                    metricas.setdefault("primera_frase", round((time.perf_counter() - t) * 1000))
                    dichas.append(frase)
                    yield _evento("frase", frase)
            except Exception as e:  # noqa: BLE001
                yield _evento("error", {"mensaje": f"El modelo '{config.LLM_MODELO}' no respondió: {e}"})
                return
            metricas["llm"] = round((time.perf_counter() - t) * 1000)
            estado["completa"] = True
            estado_caso = db.uno("SELECT estado FROM conversaciones WHERE id=%s", (cid,))
            if estado_caso and estado_caso["estado"] == "abierto":
                _cambiar_estado(cid, "orientado", "Orientación entregada en llamada en vivo")
            yield _evento("fin", {"metricas": metricas, "tipo": "llamada"})
        finally:
            guardar()                       # también si la persona interrumpió (petición cancelada)

    return StreamingResponse(flujo(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Voz
# ---------------------------------------------------------------------------
@app.post("/api/stt")
async def stt(audio: UploadFile = File(...), rapido: bool = False):
    if not voz.stt_disponible():
        raise HTTPException(501, "faster-whisper no está instalado")
    datos = await audio.read()
    modelo = config.WHISPER_LLAMADA if rapido else None      # la llamada en vivo prioriza la rapidez
    try:
        return await asyncio.to_thread(voz.transcribir, datos, modelo)
    except Exception as e:  # noqa: BLE001
        print("Error en STT:", repr(e))
        raise HTTPException(500, f"No se pudo transcribir el audio: {e}") from e


class TextoVoz(BaseModel):
    texto: str | None = None                 # texto libre: se divide en frases con emoción inferida
    segmentos: list[dict] | None = None      # guion hablado [{emocion, texto}]
    voz: str | None = None                   # id de la voz Piper (p. ej. es_AR-daniela-high o es_ES-sharvard-medium#F)
    velocidad: float = 1.0


@app.get("/api/voces")
def voces():
    return {"disponible": voz.tts_disponible(), "instaladas": voz.voces_instaladas() if voz.tts_disponible() else [],
            "catalogo": voz.catalogo(), "emociones": list(voz.PROSODIA)}


@app.post("/api/tts")
async def tts(t: TextoVoz):
    if not voz.tts_disponible():
        return JSONResponse({"detalle": "Piper no disponible; use la voz del navegador"}, status_code=501)
    segmentos = [s for s in (t.segmentos or []) if isinstance(s, dict) and s.get("texto")][:12]
    if not segmentos:
        segmentos = personalidad.segmentar_texto((t.texto or "")[:2500])
    if not segmentos:
        raise HTTPException(400, "No hay texto para leer")
    inicio = time.perf_counter()
    try:
        wav, duraciones = await asyncio.to_thread(voz.sintetizar_segmentos, segmentos, t.voz, t.velocidad)
    except Exception as e:  # noqa: BLE001
        print("Error en TTS:", repr(e))
        raise HTTPException(500, f"No se pudo generar la voz: {e}") from e
    return Response(wav, media_type="audio/wav",
                    headers={"X-TTS-ms": str(round((time.perf_counter() - inicio) * 1000)),
                             "X-Segmentos": ",".join(map(str, duraciones)),
                             "Access-Control-Expose-Headers": "X-TTS-ms, X-Segmentos"})


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
    caso = db.uno("SELECT c.id, c.estado, c.notas, c.area, c.alias, c.bloqueada, c.motivo_cierre, "
                  "p.id AS consultante_id, p.nombre, p.documento, p.telefono, "
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


HORAS = agenda.HORAS


def _ocupadas(entidad_id: int, fecha) -> set[str]:
    return {f["h"] for f in db.consultar(
        "SELECT to_char(hora,'HH24:MI') AS h FROM citas_consultorio WHERE entidad_id=%s AND fecha=%s AND estado<>'cancelada'",
        (entidad_id, fecha))}


def horas_libres(entidad_id: int, fecha) -> list[str]:
    """Horas libres de un día hábil (lunes a viernes sin festivos); un día no hábil no tiene horas."""
    d = date.fromisoformat(fecha) if isinstance(fecha, str) else fecha
    if not agenda.es_habil(d) or d <= agenda.hoy_colombia():
        return []
    ocupadas = _ocupadas(entidad_id, d)
    return [h for h in HORAS if h not in ocupadas]


@app.get("/api/citas/disponibilidad")
def disponibilidad(entidad_id: int, fecha: str):
    ocupadas = _ocupadas(entidad_id, fecha)
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
    return _insertar_cita(c.conversacion_id, pid, c.entidad_id, c.fecha, c.hora, c.modalidad, c.motivo)


def _insertar_cita(cid, pid: int, entidad_id: int, fecha: str, hora: str, modalidad: str, motivo: str | None,
                   origen: str = "formulario") -> dict:
    """Crea la cita validando el horario de atención. La usan el formulario y la agenda por voz."""
    if hora not in HORAS:
        raise HTTPException(400, "Horario no disponible")
    try:
        d = date.fromisoformat(fecha)
    except ValueError as e:
        raise HTTPException(400, "Fecha inválida") from e
    if not agenda.es_habil(d):
        raise HTTPException(400, "Solo se agenda en días hábiles (lunes a viernes, sin festivos)")
    try:
        fila = db.uno("INSERT INTO citas_consultorio (conversacion_id, consultante_id, entidad_id, fecha, hora, modalidad, motivo, origen) "
                      "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                      (cid, pid, entidad_id, fecha, hora, modalidad, motivo, origen))
    except Exception as e:  # noqa: BLE001
        if "citas_horario_uq" in str(e):
            raise HTTPException(409, "Ese horario acaba de ser tomado. Elija otro.") from e
        raise
    if cid:
        _cambiar_estado(cid, "remitido", f"Cita agendada para el {fecha} a las {hora}")
    return _cita_json(fila) | {"entidad": db.uno("SELECT nombre, horario FROM entidades WHERE id=%s", (entidad_id,))}


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
