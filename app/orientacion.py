"""Lógica del dominio: emergencias, urgencia, área jurídica y prompt."""
import math
import re
import unicodedata

from . import db


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------
# 1. Detección de emergencias (antes de cualquier LLM: seguridad primero)
# ---------------------------------------------------------------------------
EMERGENCIAS = [
    (r"\b(me (pega|golpea|golpeo|pego|maltrata)|nos pega|me (quiere|va a) matar|me amenaz\w* (de|con) muerte|"
     r"violencia (intrafamiliar|domestica)|me (violo|abuso|agredio)|abuso sexual|violaron)\b",
     "violencia", "Si está en peligro ahora, llame al 123. Línea 155 (mujeres) y 141 (niñez) atienden 24 horas."),
    (r"\b(suicid\w*|quitarme la vida|no quiero vivir|matarme)\b",
     "vida", "Su vida importa. Llame ya al 123 o a la línea 106 de apoyo en salud mental."),
    (r"\b(abus\w* (de|a) (un|una|mi) (nino|nina|hijo|hija|menor)|tocaron a mi (hijo|hija))\b",
     "menores", "Reporte de inmediato a la Línea 141 del ICBF o al 123."),
]


def detectar_emergencia(texto: str) -> dict | None:
    t = normalizar(texto)
    for patron, tipo, mensaje in EMERGENCIAS:
        if re.search(patron, t):
            return {"tipo": tipo, "mensaje": mensaje,
                    "lineas": [{"numero": "123", "nombre": "Emergencias"},
                               {"numero": "155", "nombre": "Orientación a mujeres"},
                               {"numero": "141", "nombre": "ICBF niñez"},
                               {"numero": "122", "nombre": "Fiscalía"}]}
    return None


# ---------------------------------------------------------------------------
# 2. Semáforo de urgencia (reglas explicables)
# ---------------------------------------------------------------------------
SENALES = {
    "alta": [(r"desalo\w*|me (quieren )?sac(an|ar) de la casa", "posible desalojo"),
             (r"embarg\w*", "embargo"),
             (r"cirugia|cancer|urgencia|no me (entregan|dan) (el|los) medicamento", "riesgo para la salud"),
             (r"manana (es|vence|tengo)|audiencia", "fecha inminente"),
             (r"cortaron (el|la|los) (agua|luz|gas|servicio)", "corte de servicios")],
    "media": [(r"despid\w*|me echaron", "despido"),
              (r"no me (han )?(pagad\w*|pagan)|no me da plata", "pagos pendientes"),
              (r"vence|plazo|termino", "plazo en curso"),
              (r"reportad\w*|datacredito|cobr\w*", "reporte o cobranza"),
              (r"no (me )?responde\w*|niega\w*|negaron", "negativa o silencio de una entidad"),
              (r"cuota alimentaria|alimentos", "cuota alimentaria")],
}


def evaluar_urgencia(texto: str, emergencia: dict | None) -> dict:
    if emergencia:
        return {"nivel": "critica", "razones": ["Posible riesgo para la vida o la integridad"]}
    t = normalizar(texto)
    for nivel in ("alta", "media"):
        razones = [etq for patron, etq in SENALES[nivel] if re.search(patron, t)]
        if razones:
            return {"nivel": nivel, "razones": razones[:3]}
    return {"nivel": "baja", "razones": ["No se detectan plazos inminentes"]}


# ---------------------------------------------------------------------------
# 3. Clasificación del área (embeddings de áreas + votos de los fragmentos)
# ---------------------------------------------------------------------------
def clasificar_area(sim_areas: list[dict], fragmentos: list[dict], previa: str | None = None) -> dict:
    puntajes = {a["slug"]: float(a["similitud"]) for a in sim_areas}
    for i, f in enumerate(fragmentos):
        if f["area"] in puntajes:
            puntajes[f["area"]] += 0.06 / (i + 1)
    if previa in puntajes:                       # continuidad de la conversación
        puntajes[previa] += 0.02
    # softmax con temperatura baja para obtener una distribución legible
    m = max(puntajes.values()) if puntajes else 0
    exp = {k: math.exp((v - m) / 0.03) for k, v in puntajes.items()}
    total = sum(exp.values()) or 1
    meta = {a["slug"]: a for a in sim_areas}
    distribucion = sorted(
        ({"slug": k, "nombre": meta[k]["nombre"], "color": meta[k]["color"],
          "simbolo": meta[k]["simbolo"], "probabilidad": round(v / total, 3)} for k, v in exp.items()),
        key=lambda x: -x["probabilidad"])
    return {"principal": distribucion[0] if distribucion else None, "distribucion": distribucion[:5]}


def ruta_y_entidades(area: str) -> tuple[list[dict], list[dict]]:
    ruta = db.consultar("SELECT orden, titulo, detalle, plazo FROM rutas WHERE area_slug=%s ORDER BY orden", (area,))
    entidades = db.consultar(
        "SELECT nombre, tipo, municipio, contacto, canal, nota FROM entidades WHERE %s = ANY(areas) "
        "ORDER BY (municipio='Nacional'), nombre LIMIT 5", (area,))
    return ruta, entidades


# ---------------------------------------------------------------------------
# 4. Prompt del sistema
# ---------------------------------------------------------------------------
SISTEMA = """Eres AMPARO, un agente de orientación jurídica básica para personas en Colombia (región Putumayo).
Hablas en español claro, cálido y respetuoso (trato de "usted"). No eres abogado: orientas, no representas.

REGLAS:
1. Usa SOLO la información de las FUENTES. Si no alcanza, dilo y recomienda un consultorio jurídico gratuito o la Personería.
2. Cita las fuentes con [1], [2]... justo después de la idea que respaldan. Nunca inventes números de leyes, artículos ni plazos.
3. Si faltan datos clave del caso, haz UNA pregunta concreta al final.
4. No prometas resultados. No pidas datos sensibles innecesarios.

FORMATO (markdown breve, máximo ~220 palabras):
**En pocas palabras:** una o dos frases con la orientación principal.
**Lo que dice la norma:** 2 o 3 viñetas con citas [n].
**Qué puede hacer:** pasos numerados, concretos, con plazos si las fuentes los dan.
**A dónde acudir:** entidades gratuitas pertinentes."""

ESTILO = {
    "sencillo": "Explica como a alguien sin estudios de derecho; evita tecnicismos o explícalos entre paréntesis.",
    "tecnico": "Usa terminología jurídica precisa e incluye la norma y el artículo cuando la fuente lo indique.",
}


def construir_mensajes(pregunta: str, fragmentos: list[dict], historial: list[dict],
                       area: dict | None, modo: str) -> list[dict]:
    bloques = []
    for i, f in enumerate(fragmentos, 1):
        bloques.append(f"[{i}] {f['titulo']} — {f['seccion']} ({f['fuente']})\n{f['contenido']}")
    contexto = "\n\n".join(bloques) if bloques else "(sin fuentes relevantes)"
    area_txt = f"Área probable del caso: {area['nombre']}." if area else ""
    mensajes = [{"role": "system", "content": SISTEMA + "\n\nESTILO: " + ESTILO.get(modo, ESTILO["sencillo"])}]
    for m in historial[-6:]:
        mensajes.append({"role": "user" if m["rol"] == "usuario" else "assistant", "content": m["contenido"]})
    mensajes.append({"role": "user", "content": f"FUENTES:\n{contexto}\n\n{area_txt}\n\nCONSULTA DE LA PERSONA:\n{pregunta}"})
    return mensajes


REDACCION = """Eres un asistente que redacta la sección de HECHOS de un documento jurídico colombiano
({tipo}). Reescribe el relato de la persona en primera persona, en párrafos numerados (PRIMERO, SEGUNDO...),
con lenguaje formal, claro y objetivo. Conserva fechas, nombres y cifras. No inventes hechos. No agregues
peticiones ni fundamentos de derecho. Devuelve solo los hechos."""
