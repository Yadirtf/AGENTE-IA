"""Agenda de citas por voz: Amparo agenda la cita ella misma durante la llamada.

El flujo es un diálogo guiado (llenado de casillas) y no depende del LLM: con un modelo pequeño en CPU
es más rápido y nunca inventa horarios. En cada turno se interpreta lo que dijo la persona, se valida
contra los días hábiles (sin sábados, domingos ni festivos de Colombia) y contra las horas libres de la
entidad, y se responde con frases cortas listas para la voz.

Este módulo no toca la base de datos: recibe un `Contexto` con las funciones que la consultan, así se
puede probar sin PostgreSQL (ver `scripts/probar_agenda.py`).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable

COLOMBIA = timezone(timedelta(hours=-5))      # Colombia no tiene horario de verano
HORAS = ["08:00", "09:00", "10:00", "11:00", "14:00", "15:00", "16:00"]
DIAS_MAXIMOS = 45                              # no se agenda más allá de este número de días calendario
PASOS = ("entidad", "fecha", "hora", "modalidad", "nombre", "telefono", "documento", "autorizacion")

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]
MODALIDADES = {"presencial": "presencial", "virtual": "virtual", "telefonica": "por teléfono"}


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------
# Calendario: festivos de Colombia (Ley 51 de 1983), igual que web/terminos.js
# ---------------------------------------------------------------------------
def _pascua(anio: int) -> date:
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mes = (h + l_ - 7 * m + 114) // 31
    dia = (h + l_ - 7 * m + 114) % 31 + 1
    return date(anio, mes, dia)


_FESTIVOS: dict[int, dict[date, str]] = {}


def festivos(anio: int) -> dict[date, str]:
    if anio in _FESTIVOS:
        return _FESTIVOS[anio]
    f: dict[date, str] = {}

    def lunes_siguiente(d: date) -> date:
        return d + timedelta(days=(7 - d.weekday()) % 7)

    for m, d, n in ((1, 1, "Año Nuevo"), (5, 1, "Día del Trabajo"), (7, 20, "Día de la Independencia"),
                    (8, 7, "Batalla de Boyacá"), (12, 8, "Inmaculada Concepción"), (12, 25, "Navidad")):
        f[date(anio, m, d)] = n
    for m, d, n in ((1, 6, "Reyes Magos"), (3, 19, "San José"), (6, 29, "San Pedro y San Pablo"),
                    (8, 15, "la Asunción"), (10, 12, "Día de la Raza"), (11, 1, "Todos los Santos"),
                    (11, 11, "Independencia de Cartagena")):
        f[lunes_siguiente(date(anio, m, d))] = n
    p = _pascua(anio)
    for dias, n in ((-3, "Jueves Santo"), (-2, "Viernes Santo"), (43, "la Ascensión"),
                    (64, "Corpus Christi"), (71, "Sagrado Corazón")):
        f[p + timedelta(days=dias)] = n
    _FESTIVOS[anio] = f
    return f


def es_festivo(d: date) -> str | None:
    return festivos(d.year).get(d)


def es_habil(d: date) -> bool:
    return d.weekday() < 5 and not es_festivo(d)


def hoy_colombia() -> date:
    return datetime.now(COLOMBIA).date()


# ---------------------------------------------------------------------------
# Números en palabras (para leer y para entender lo que dice la persona)
# ---------------------------------------------------------------------------
_UNIDADES = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
             "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve",
             "veinte", "veintiuno", "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis",
             "veintisiete", "veintiocho", "veintinueve"]
_DECENAS = {30: "treinta", 40: "cuarenta", 50: "cincuenta", 60: "sesenta", 70: "setenta", 80: "ochenta",
            90: "noventa"}
_CENTENAS = {100: "cien", 200: "doscientos", 300: "trescientos", 400: "cuatrocientos", 500: "quinientos",
             600: "seiscientos", 700: "setecientos", 800: "ochocientos", 900: "novecientos"}


def en_palabras(n: int) -> str:
    if n < 30:
        return _UNIDADES[n]
    if n < 100:
        d, u = n // 10 * 10, n % 10
        return _DECENAS[d] + (f" y {_UNIDADES[u]}" if u else "")
    if n < 1000:
        c, r = n // 100 * 100, n % 100
        base = "ciento" if c == 100 and r else _CENTENAS[c]
        return base + (f" {en_palabras(r)}" if r else "")
    return str(n)


# Palabra → (valor, tipo). tipo: u = unidad (0-9), e = 10-29, d = decena, c = centena
_PALABRAS: dict[str, tuple[int, str]] = {}
for _i, _p in enumerate(_UNIDADES):
    _PALABRAS[normalizar(_p)] = (_i, "u" if _i < 10 else "e")
_PALABRAS.update({"un": (1, "u"), "una": (1, "u"), "primero": (1, "u"), "veintiun": (21, "e")})
for _v, _p in _DECENAS.items():
    _PALABRAS[_p] = (_v, "d")
for _v, _p in _CENTENAS.items():
    _PALABRAS[normalizar(_p)] = (_v, "c")
_PALABRAS.update({"ciento": (100, "c"), "quinientas": (500, "c"), "doscientas": (200, "c")})


def numeros_hablados(texto: str) -> list[int]:
    """Convierte números dichos con palabras o dígitos en una lista de enteros, en orden.

    "tres diez cuatro cincuenta y dos" → [3, 10, 4, 52]; "el 17" → [17].
    """
    return [int(x) for x in _numeros_texto(texto)]


def _numeros_texto(texto: str) -> list[str]:
    """Como numeros_hablados, pero conserva los ceros a la izquierda de lo dicho en dígitos ("000")."""
    tokens = re.findall(r"\d+|[a-zñ]+", normalizar(texto))
    salida: list[int] = []
    actual: int | None = None
    ultimo = ""
    for tok in tokens:
        if tok.isdigit():
            if actual is not None:
                salida.append(str(actual))
                actual = None
            salida.append(tok)
            ultimo = "n"
            continue
        if tok == "y" and actual is not None and ultimo == "d":
            continue
        if tok not in _PALABRAS:
            if actual is not None:
                salida.append(str(actual))
                actual = None
            ultimo = ""
            continue
        valor, tipo = _PALABRAS[tok]
        if actual is not None and (
            (ultimo == "c" and tipo in "ued") or (ultimo == "d" and tipo == "u" and actual % 10 == 0)
        ):
            actual += valor
        else:
            if actual is not None:
                salida.append(str(actual))
            actual = valor
        ultimo = tipo
    if actual is not None:
        salida.append(str(actual))
    return salida


def digitos_hablados(texto: str) -> str:
    """Todos los dígitos que dijo la persona, en orden: «tres diez, cero cero» → "31000"."""
    return "".join(_numeros_texto(texto))


def leer_digitos(digitos: str) -> str:
    """Lee un número dígito por dígito, en grupos, para que la voz lo diga claro."""
    grupos = [digitos[i:i + 3] for i in range(0, len(digitos), 3)]
    if len(grupos) > 1 and len(grupos[-1]) == 1:             # evita un dígito suelto al final
        grupos[-2:] = [grupos[-2] + grupos[-1]]
    return ", ".join(" ".join(_UNIDADES[int(c)] for c in g) for g in grupos)


def fecha_hablada(d: date, con_mes: bool = True) -> str:
    dia = "primero" if d.day == 1 else en_palabras(d.day)
    return f"{DIAS[d.weekday()]} {dia}" + (f" de {MESES[d.month - 1]}" if con_mes else "")


def hora_hablada(h: str) -> str:
    n = int(h[:2])
    if n == 12:
        return "las doce del mediodía"
    if n == 13 or n == 1:
        return "la una de la tarde"
    return f"las {en_palabras(n if n < 12 else n - 12)} de la {'mañana' if n < 12 else 'tarde'}"


def horas_habladas(horas: list[str]) -> str:
    man = [en_palabras(int(h[:2])) for h in horas if int(h[:2]) < 12]
    tar = [en_palabras(int(h[:2]) - 12) for h in horas if int(h[:2]) >= 12]

    def lista(xs: list[str]) -> str:
        return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " y " + xs[-1]

    partes = []
    if man:
        partes.append(f"{'a la' if man == ['uno'] else 'a las'} {lista(man)} de la mañana")
    if tar:
        partes.append(f"{'a la' if tar == ['uno'] else 'a las'} {lista(tar)} de la tarde")
    return " y ".join(partes) if len(partes) < 2 else f"{partes[0]}, y {partes[1]}"


# ---------------------------------------------------------------------------
# Interpretación de lo que dice la persona
# ---------------------------------------------------------------------------
_SI = re.compile(r"\b(si|sii|claro|dale|listo|correcto|confirm\w*|de una|ok|okay|perfecto|exacto|asi es|bueno|"
                 r"esta bien|hagale|por supuesto|acepto|autorizo|de acuerdo|vale|eso es|afirmativo)\b")
_NO = re.compile(r"\b(no|nop|nope|negativo|todavia no|espere|cambi\w*|mejor|corrij\w*|equivoc\w*)\b")
_CANCELAR = re.compile(r"\b(cancel\w*|olvid\w*|ya no (quiero|necesito)|dejelo|dejemoslo|deje asi|no quiero (la |una |ninguna )?cita|"
                       r"despues la agendo|en otro momento|mejor despues|no gracias,? (asi|ya))\b")
_INTENCION = re.compile(
    r"\bagend\w*\b|\b(quiero|quisiera|necesito|me gustaria|deseo|pedir|pido|sacar|saco|separar|reservar|apartar|"
    r"programar|solicitar|hacer|darme|deme|me da|me puede dar|tener)\b[^.?!]{0,30}\bcita\b|"
    r"\bcita\b[^.?!]{0,25}\b(consultorio|abogad\w*|gratuita|gratis|personeria|defensoria|casa de justicia|comisaria)\b")
_CITA_MEDICA = re.compile(r"\bcita\w* (medica|con el (medico|especialista)|en la eps|de la eps|con la eps|odontolog\w*)\b|"
                          r"\b(eps|hospital|clinica|medico)\b[^.]{0,30}\bcita\b")
_OFRECE = re.compile(r"\b(le agend\w*|agendar\w*|la agend\w*|una cita)\b")


def quiere_agendar(texto: str) -> bool:
    t = normalizar(texto)
    if _CITA_MEDICA.search(t) and not re.search(r"\b(consultorio|abogad\w*|agendeme|agendarme)\b", t):
        return False
    return bool(_INTENCION.search(t))


def acepta_oferta(texto: str, ultima_de_amparo: str | None) -> bool:
    """¿La persona dijo que sí justo después de que Amparo le ofreció agendar?"""
    if not ultima_de_amparo or "?" not in ultima_de_amparo:
        return False
    if not _OFRECE.search(normalizar(ultima_de_amparo)):
        return False
    t = normalizar(texto)
    return len(t.split()) <= 8 and bool(_SI.search(t)) and not re.search(r"\bno\b", t)


def es_si(texto: str) -> bool | None:
    t = normalizar(texto)
    no, si = bool(_NO.search(t)), bool(_SI.search(t))
    if re.search(r"\b(no autorizo|no acepto|no esta bien|no es correcto|no,? no)\b", t):
        return False
    if si and not no:
        return True
    if no and not si:
        return False
    if si and no:            # «sí, pero mejor el viernes» / «no, sí está bien»: decide la primera palabra
        primera = re.search(r"\b(si|no|claro|dale|listo|correcto|cambi\w*|mejor)\b", t)
        return bool(primera) and primera.group(1) in ("si", "claro", "dale", "listo", "correcto")
    return None


ENTIDADES_CLAVE = (
    (r"consultorio|universi", "consultorio"),
    (r"casa de (la )?justicia", "casa de justicia"),
    (r"comisari", "comisar"),
    (r"personeri", "personer"),
    (r"defensori", "defensor"),
)
# Pistas más sueltas: solo cuando Amparo está preguntando el lugar
ENTIDADES_PISTAS = ((r"estudiant|abogad|universidad", "consultorio"), (r"\bfamilia\b", "comisar"),
                    (r"\bjusticia\b", "casa de justicia"), (r"defensor", "defensor"))


def buscar_entidad(texto: str, entidades: list[dict], pistas: bool = False) -> dict | None:
    t = normalizar(texto)
    for patron, clave in ENTIDADES_CLAVE + (ENTIDADES_PISTAS if pistas else ()):
        if re.search(patron, t):
            for e in entidades:
                if clave in normalizar(e["nombre"]):
                    return e
    return None


def buscar_modalidad(texto: str) -> str | None:
    t = normalizar(texto)
    if re.search(r"\b(virtual\w*|video\w*|videollamada|meet|zoom|internet|en linea|computador)\b", t):
        return "virtual"
    if re.search(r"\b(telefon\w*|por celular|llamada|llamad\w*|que me llamen)\b", t):
        return "telefonica"
    if re.search(r"\b(presencial\w*|en persona|personalmente|ir (alla|hasta)|voy|asistir|alla mismo|cara a cara)\b", t):
        return "presencial"
    return None


_DIAS_N = [normalizar(d) for d in DIAS]
_MESES_N = [normalizar(m) for m in MESES]


def buscar_fecha(texto: str, hoy: date, solo_explicita: bool = False) -> date | None:
    """Interpreta «mañana», «el jueves», «el próximo lunes», «el 17», «diecisiete de noviembre»…

    Con `solo_explicita` no toma un número suelto (podría ser la hora o un teléfono).
    """
    t = re.sub(r"\bun[a]?\b", " ", normalizar(texto))     # «una semana» no es el día 1
    if re.search(r"\bpasado manana\b", t):
        return hoy + timedelta(days=2)
    if re.search(r"(?<!la )\bmanana\b", t):
        return hoy + timedelta(days=1)
    if re.search(r"\bhoy\b", t):
        return hoy
    # «el 17 de noviembre», «diecisiete de noviembre»
    m = re.search(r"([a-z0-9 ]+?)\s+de\s+(" + "|".join(_MESES_N) + r")\b", t)
    if m:
        nums = numeros_hablados(m.group(1).split(" del ")[-1])
        mes = _MESES_N.index(m.group(2)) + 1
        if nums and 1 <= nums[-1] <= 31:
            anio = hoy.year + (1 if mes < hoy.month else 0)
            try:
                return date(anio, mes, nums[-1])
            except ValueError:
                return None
    # Día de la semana, con o sin número: «el jueves», «el jueves doce», «el próximo lunes»
    m = re.search(r"\b(" + "|".join(_DIAS_N) + r")\b", t)
    if m:
        dow = _DIAS_N.index(m.group(1))
        resto = t[m.end():m.end() + 25]
        nums = [n for n in numeros_hablados(resto.split(" a las ")[0]) if 1 <= n <= 31]
        if nums:
            d = _dia_del_mes(nums[0], hoy)
            if d:
                return d
        dias = (dow - hoy.weekday()) % 7 or 7
        if re.search(r"\b(la otra semana|en ocho dias|subsiguiente)\b", t) and dias < 7:
            dias += 7
        return hoy + timedelta(days=dias)
    if solo_explicita:
        m = re.search(r"\bel dia\s+(\S+)", t)
        nums = [n for n in numeros_hablados(m.group(1)) if 1 <= n <= 31] if m else []
        return _dia_del_mes(nums[0], hoy) if nums else None
    nums = [n for n in numeros_hablados(t) if 1 <= n <= 31]
    if nums:
        return _dia_del_mes(nums[0], hoy)
    return None


def _dia_del_mes(dia: int, hoy: date) -> date | None:
    anio, mes = hoy.year, hoy.month
    if dia <= hoy.day:
        mes += 1
        if mes > 12:
            anio, mes = anio + 1, 1
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def pide_lo_antes_posible(texto: str) -> bool:
    return bool(re.search(r"\b(lo (mas )?(antes|pronto)|cuanto antes|primer\w* (dia|cupo|que)|mas cercan\w*|cualquier\w*|"
                          r"el que (sea|usted|diga|haya)|como (usted|quiera)|me da igual|cuando (sea|haya))\b",
                          normalizar(texto)))


def buscar_hora(texto: str, solo_explicita: bool = False) -> tuple[str | None, str | None]:
    """Devuelve (hora "HH:MM", franja). franja es "manana"/"tarde" si solo dijo la parte del día.

    Con `solo_explicita` solo toma horas dichas como «a las …», «… de la mañana/tarde» o «HH:MM».
    """
    t = re.sub(r"\b([ap])\.\s?m\b\.?", r"\1m", normalizar(texto))
    tarde = bool(re.search(r"\b(de la tarde|en la tarde|por la tarde|pm|p m)\b", t))
    manana = bool(re.search(r"\b(de la manana|en la manana|por la manana|temprano|am|a m)\b", t))
    m = re.search(r"\b(\d{1,2})(?::|\.|h)(\d{2})\b", t)
    if m:
        h, mins = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"\ba (las|la)\s+([a-z0-9]+(?: y [a-z]+)?)", t) or re.search(
            r"\b([a-z0-9]+)\s+(?:en punto\s+)?(?:de la (?:manana|tarde)|en punto|am|pm)\b", t)
        if m:
            nums = numeros_hablados(m.group(m.lastindex))
            h = nums[0] if nums else None
        elif not solo_explicita:
            nums = [n for n in numeros_hablados(t) if 1 <= n <= 23]
            h = nums[0] if nums else None
        else:
            h = None
        mins = 30 if h is not None and re.search(r"\by media\b", t) else 0
        if re.search(r"\bmediodia\b", t) and h is None:
            h = 12
    if h is None:
        return None, ("tarde" if tarde else "manana" if manana else None)
    if tarde and h < 12:
        h += 12
    elif not manana and 1 <= h <= 7:     # «a las dos» en horario de oficina es de la tarde
        h += 12
    if not 0 <= h <= 23:
        return None, None
    return f"{h:02d}:{mins:02d}", None


_MULETILLA = re.compile(r"^((pues|bueno|si|sí|claro|ok|listo|eh+|este|mire|ah|ya)\b[\s,]*)+", re.I)
_RELLENO_NOMBRE = re.compile(
    r"^(mi nombre (completo )?es|me llamo|soy|yo soy|"
    r"a nombre de|ponga(la)? a nombre de|es|el nombre es|se llama|sera a nombre de)\s+", re.I)


def limpiar_nombre(texto: str) -> str | None:
    t = re.sub(r"[.,;:!?¡¿\"]", " ", texto).strip()
    t = _RELLENO_NOMBRE.sub("", _MULETILLA.sub("", t)).strip()
    t = re.sub(r"\s+(gracias|por favor|nada mas|y ya)\s*$", "", t, flags=re.I).strip()
    palabras = [p for p in t.split() if p]
    if not palabras or len(palabras) > 6:
        return None
    if not all(re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ'-]+", p) for p in palabras):
        return None
    if normalizar(palabras[0]) in ("no", "si", "que", "como", "cual", "para", "cancelar", "a", "el", "la", "en"):
        return None
    if all(normalizar(p) in _PALABRAS or normalizar(p) == "y" for p in palabras):     # «nueve» no es un nombre
        return None
    minus = {"de", "del", "la", "las", "los", "y"}
    return " ".join(p.lower() if p.lower() in minus and i else p[:1].upper() + p[1:].lower()
                    for i, p in enumerate(palabras))


# ---------------------------------------------------------------------------
# El diálogo
# ---------------------------------------------------------------------------
@dataclass
class Contexto:
    entidades: list[dict]                                   # [{id, nombre, horario}] que atienden citas
    horas_libres: Callable[[int, date], list[str]]          # entidad_id, fecha → ["08:00", …]
    crear: Callable[[dict], dict]                           # datos de la cita → fila creada (o lanza HorarioOcupado)
    hoy: date = field(default_factory=hoy_colombia)
    alias: str | None = None


class HorarioOcupado(Exception):
    pass


@dataclass
class Resultado:
    frases: list[dict]
    estado: dict | None                                     # None cuando la agenda terminó o se canceló
    cita: dict | None = None                                # la cita creada, si se creó en este turno
    cancelada: bool = False


def con_articulo(nombre: str) -> str:
    """«la Casa de Justicia», «el Consultorio jurídico universitario»."""
    return ("la " if nombre.split()[0].lower().endswith("a") else "el ") + nombre


def _f(emocion: str, texto: str) -> dict:
    return {"emocion": emocion, "texto": texto}


def nuevo_estado(motivo: str | None) -> dict:
    return {"paso": None, "entidad_id": None, "entidad": None, "fecha": None, "hora": None, "modalidad": None,
            "nombre": None, "telefono": None, "documento": None, "sin_documento": False, "autorizacion": None,
            "motivo": (motivo or "")[:400] or None, "fallos": 0}


def resumen_publico(e: dict) -> dict:
    """Lo que se muestra en pantalla mientras se agenda (sin cédula completa)."""
    doc = e.get("documento")
    return {"paso": e.get("paso"), "entidad": e.get("entidad"), "fecha": e.get("fecha"), "hora": e.get("hora"),
            "modalidad": e.get("modalidad"), "nombre": e.get("nombre"), "telefono": e.get("telefono"),
            "documento": ("•••" + doc[-3:]) if doc else ("sin cédula" if e.get("sin_documento") else None),
            "autorizacion": e.get("autorizacion")}


def _dias_con_cupo(ctx: Contexto, entidad_id: int, desde: date, n: int = 3) -> list[date]:
    dias, d = [], desde
    while len(dias) < n and (d - ctx.hoy).days <= DIAS_MAXIMOS:
        d += timedelta(days=1)
        if es_habil(d) and ctx.horas_libres(entidad_id, d):
            dias.append(d)
    return dias


def _lista_dias(dias: list[date]) -> str:
    mes_unico = len({d.month for d in dias}) == 1
    partes = [("el " + fecha_hablada(d, con_mes=not mes_unico)) for d in dias]
    texto = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]
    return texto + (f" de {MESES[dias[0].month - 1]}" if mes_unico else "")


def _pregunta(ctx: Contexto, e: dict) -> list[dict]:
    """La pregunta del paso actual."""
    paso = e["paso"]
    if paso == "entidad":
        nombres = [x["nombre"] for x in ctx.entidades]
        corto = [re.sub(r" (de Mocoa|· Regional Putumayo|universitario)$", "", n) for n in nombres]
        lista = ", ".join(corto[:-1]) + " o " + corto[-1] if len(corto) > 1 else corto[0]
        return [_f("tranquila", f"Puedo agendarle en: {lista}."),
                _f("calida", "¿Dónde la prefiere? Si no está seguro, le recomiendo el consultorio jurídico.")]
    if paso == "fecha":
        dias = _dias_con_cupo(ctx, e["entidad_id"], ctx.hoy)
        if not dias:
            return [_f("seria", "Uy, no encuentro cupos libres en las próximas semanas en ese lugar."),
                    _f("calida", "¿Quiere que probemos en otra entidad?")]
        return [_f("tranquila", f"Atienden de lunes a viernes, sin festivos. Tengo cupo {_lista_dias(dias)}."),
                _f("calida", "¿Qué día le queda mejor?")]
    if paso == "hora":
        d = date.fromisoformat(e["fecha"])
        libres = ctx.horas_libres(e["entidad_id"], d)
        return [_f("tranquila", f"Para el {fecha_hablada(d, False)} tengo libre {horas_habladas(libres)}."),
                _f("calida", "¿A qué hora le sirve?")]
    if paso == "modalidad":
        return [_f("calida", "¿La cita la quiere presencial, virtual o por teléfono?")]
    if paso == "nombre":
        return [_f("calida", "¿A nombre de quién la agendo? Dígame su nombre completo, por favor.")]
    if paso == "telefono":
        return [_f("calida", "¿A qué número de celular le pueden llamar para confirmarle?")]
    if paso == "documento":
        return [_f("tranquila", "Si quiere, dígame su número de cédula. Si prefiere no darlo, diga «sin cédula».")]
    if paso == "autorizacion":
        return [_f("seria", "Una última cosa: ¿autoriza que guardemos sus datos solo para gestionar esta cita, "
                            "como dice la Ley 1581 de 2012?")]
    if paso == "confirmar":
        return [_f("tranquila", _repaso(e)), _f("calida", "¿Se la confirmo?")]
    if paso == "corregir":
        return [_f("calida", "Claro. ¿Qué quiere cambiar: el lugar, el día, la hora, la modalidad o sus datos?")]
    return []


def _repaso(e: dict) -> str:
    d = date.fromisoformat(e["fecha"])
    modo = {"presencial": "presencial", "virtual": "virtual", "telefonica": "por teléfono"}[e["modalidad"]]
    return (f"Le repaso: cita {modo} en {con_articulo(e['entidad'])}, el {fecha_hablada(d)} a {hora_hablada(e['hora'])}, "
            f"a nombre de {e['nombre']}, celular {leer_digitos(e['telefono'])}.")


def _siguiente(e: dict) -> str:
    for paso in PASOS:
        if paso == "documento":
            if not e["documento"] and not e["sin_documento"]:
                return paso
        elif e.get(paso) is None:
            return paso
    return "confirmar"


def _validar_fecha(ctx: Contexto, e: dict, d: date) -> list[dict] | None:
    """Devuelve frases de rechazo si el día no sirve; None si sirve."""
    alternativa = _dias_con_cupo(ctx, e["entidad_id"], d if d > ctx.hoy else ctx.hoy, 2)
    otra = f" ¿Le sirve el {fecha_hablada(alternativa[0])}?" if alternativa else ""
    if d <= ctx.hoy:
        return [_f("calida", "Para hoy ya no puedo agendar; las citas son desde mañana." + otra)]
    if (d - ctx.hoy).days > DIAS_MAXIMOS:
        return [_f("calida", "Esa fecha está muy lejos; agendo máximo con seis semanas de anticipación." + otra)]
    if d.weekday() >= 5:
        return [_f("calida", f"El {DIAS[d.weekday()]} no atienden: solo de lunes a viernes." + otra)]
    festivo = es_festivo(d)
    if festivo:
        return [_f("calida", f"El {fecha_hablada(d)} es festivo, por {festivo}, y no atienden." + otra)]
    if not ctx.horas_libres(e["entidad_id"], d):
        return [_f("calida", f"El {fecha_hablada(d, False)} ya está lleno." + otra)]
    return None


def _aplicar_fecha(ctx: Contexto, e: dict, d: date, dichas: list[dict]) -> bool:
    rechazo = _validar_fecha(ctx, e, d)
    if rechazo:
        dichas.extend(rechazo)
        e["fecha"], e["hora"], e["sugerida"] = None, None, None
        alt = _dias_con_cupo(ctx, e["entidad_id"], d if d > ctx.hoy else ctx.hoy, 1)
        if alt:
            e["sugerida"] = alt[0].isoformat()
        return False
    if e["fecha"] != d.isoformat():
        e["fecha"], e["hora"] = d.isoformat(), None
    e.pop("sugerida", None)
    pedida = e.pop("hora_pedida", None)          # la hora que dijo para un día que no servía
    if pedida and not e["hora"] and pedida in ctx.horas_libres(e["entidad_id"], d):
        e["hora"] = pedida
    return True


def _aplicar_hora(ctx: Contexto, e: dict, h: str | None, franja: str | None, dichas: list[dict]) -> bool:
    d = date.fromisoformat(e["fecha"])
    libres = ctx.horas_libres(e["entidad_id"], d)
    if h is None and franja:
        opciones = [x for x in libres if (int(x[:2]) < 12) == (franja == "manana")]
        if not opciones:
            e["hora"] = None
            dichas.append(_f("calida", f"En la {'mañana' if franja == 'manana' else 'tarde'} ya no hay cupo ese día. "
                                       f"Me queda {horas_habladas(libres)}. ¿Cuál le sirve?"))
            return False
        h = opciones[0]
    if h is None:
        return False
    if h in libres:
        e["hora"] = h
        return True
    e["hora"] = None
    if h.endswith(":30"):
        texto = "Las citas son a la hora en punto."
    elif h in HORAS:
        texto = f"A {hora_hablada(h)} ya está ocupado."
    else:
        texto = "A esa hora no atienden: es de ocho a doce y de dos a cinco."
    dichas.append(_f("calida", f"{texto} Ese día me queda {horas_habladas(libres)}. ¿Cuál prefiere?"))
    return False


def procesar(texto: str, estado: dict | None, ctx: Contexto, motivo: str | None = None) -> Resultado:
    """Un turno de la agenda. Si `estado` es None, empieza la agenda."""
    dichas: list[dict] = []
    t = normalizar(texto)
    if estado is None:
        e = nuevo_estado(motivo)
        dichas.append(_f("alegre", "¡Con mucho gusto le agendo la cita! Es gratuita y le toma un minuto."))
        if len(ctx.entidades) == 1:
            e["entidad_id"], e["entidad"] = ctx.entidades[0]["id"], ctx.entidades[0]["nombre"]
        _extraer(texto, e, ctx, dichas, inicio=True)
        return _avanzar(e, ctx, dichas)

    e = dict(estado)
    paso = e.get("paso")
    if _CANCELAR.search(t) and paso not in ("autorizacion",):
        return Resultado([_f("calida", "Listo, no le agendo nada por ahora."),
                          _f("calida", "Cuando quiera, me dice «quiero agendar una cita» y la hacemos. ¿Le ayudo con algo más?")],
                         None, cancelada=True)

    entendido = False
    cambio = buscar_entidad(texto, ctx.entidades) if paso in ("fecha", "hora", "modalidad") else None
    if cambio and cambio["id"] != e["entidad_id"]:
        e["entidad_id"], e["entidad"], e["fecha"], e["hora"], entendido = cambio["id"], cambio["nombre"], None, None, True
        _extraer(texto, e, ctx, dichas)
    elif paso == "entidad":
        ent = buscar_entidad(texto, ctx.entidades, pistas=True)
        if not ent and (pide_lo_antes_posible(texto) or es_si(texto) or re.search(r"\b(no se|recomiend\w*|ese|esa)\b", t)):
            ent = next((x for x in ctx.entidades if "consultorio" in normalizar(x["nombre"])), ctx.entidades[0])
        if ent:
            e["entidad_id"], e["entidad"], entendido = ent["id"], ent["nombre"], True
            _extraer(texto, e, ctx, dichas)
    elif paso == "fecha":
        d = buscar_fecha(texto, ctx.hoy)
        if d is None and e.get("sugerida") and es_si(texto):
            d = date.fromisoformat(e["sugerida"])
        if d is None and pide_lo_antes_posible(texto):
            dias = _dias_con_cupo(ctx, e["entidad_id"], ctx.hoy, 1)
            d = dias[0] if dias else None
        if d is not None:
            entendido = True
            if _aplicar_fecha(ctx, e, d, dichas):
                h, franja = buscar_hora(texto, solo_explicita=True)
                if h or franja:
                    _aplicar_hora(ctx, e, h, franja, dichas)
                e["modalidad"] = e["modalidad"] or buscar_modalidad(texto)
    elif paso == "hora":
        h, franja = buscar_hora(texto)
        if h is None and franja is None and pide_lo_antes_posible(texto):
            libres = ctx.horas_libres(e["entidad_id"], date.fromisoformat(e["fecha"]))
            h = libres[0] if libres else None
        otra_fecha = buscar_fecha(texto, ctx.hoy, solo_explicita=True)
        if otra_fecha and otra_fecha.isoformat() != e["fecha"]:
            entendido = True
            _aplicar_fecha(ctx, e, otra_fecha, dichas)
            if e["fecha"] == otra_fecha.isoformat():
                h, franja = buscar_hora(texto, solo_explicita=True)
                if h or franja:
                    _aplicar_hora(ctx, e, h, franja, dichas)
        elif h or franja:
            entendido = True
            _aplicar_hora(ctx, e, h, franja, dichas)
            e["modalidad"] = e["modalidad"] or buscar_modalidad(texto)
    elif paso == "modalidad":
        m = buscar_modalidad(texto) or ("presencial" if (es_si(texto) or pide_lo_antes_posible(texto)) else None)
        if m:
            e["modalidad"], entendido = m, True
    elif paso == "nombre":
        if ctx.alias and re.search(r"\b(el mismo|ya (le|se lo) dije|como le dije|el que le di)\b", t):
            nombre = ctx.alias
        else:
            nombre = limpiar_nombre(texto)
        if nombre:
            e["nombre"], entendido = nombre, True
    elif paso == "telefono":
        dig = digitos_hablados(texto)
        if 7 <= len(dig) <= 10:
            e["telefono"], entendido = dig, True
        elif dig:
            entendido = True
            dichas.append(_f("calida", f"Me quedaron {en_palabras(len(dig))} dígitos y el celular tiene diez. "
                                       "¿Me lo repite despacio, por favor?"))
    elif paso == "documento":
        dig = digitos_hablados(texto)
        if 5 <= len(dig) <= 12:
            e["documento"], entendido = dig, True
        elif re.search(r"\b(sin cedula|no|prefiero no|despues|no la tengo|no tengo|no quiero|paso|sigamos|siga)\b", t):
            e["sin_documento"], entendido = True, True
    elif paso == "autorizacion":
        r = es_si(texto)
        if r is True:
            e["autorizacion"], entendido = True, True
        elif r is False or _CANCELAR.search(t):
            return Resultado([_f("calida", "Entiendo. Sin su autorización no puedo guardar la cita, así que no la agendo."),
                              _f("calida", "Si cambia de opinión, me dice «quiero agendar una cita». ¿Le ayudo con algo más?")],
                             None, cancelada=True)
    elif paso == "confirmar":
        r = es_si(texto)
        antes = dict(e)
        _extraer(texto, e, ctx, dichas)
        if e != antes:                                   # «no, mejor el viernes»: cambió algo concreto
            entendido = True
        elif r is True:
            return _crear(e, ctx)
        elif r is False:
            e["paso"], entendido = "corregir", True
            return Resultado(dichas + _pregunta(ctx, e), e)
    elif paso == "corregir":
        antes = dict(e)
        _extraer(texto, e, ctx, dichas)
        if e != antes:
            entendido = True
        for patron, campos in ((r"\b(lugar|entidad|sitio|donde)\b", ("entidad_id", "entidad", "fecha", "hora")),
                               (r"\b(dia|fecha)\b", ("fecha", "hora")), (r"\bhora\b", ("hora",)),
                               (r"\b(modalidad|presencial|virtual|telefon\w*)\b", ("modalidad",)),
                               (r"\bnombre\b", ("nombre",)), (r"\b(telefono|celular|numero)\b", ("telefono",)),
                               (r"\b(cedula|documento)\b", ("documento",))):
            if re.search(patron, t) and e == antes:
                for c in campos:
                    e[c] = None
                if "documento" in campos:
                    e["sin_documento"] = False
                entendido = True
        if not entendido and re.search(r"\b(dato\w*)\b", t):
            e["nombre"] = e["telefono"] = e["documento"] = None
            e["sin_documento"], entendido = False, True
        if not entendido and (es_si(texto) is True or re.search(r"\b(nada|esta bien)\b", t)):
            e["paso"] = "confirmar"
            return _crear(e, ctx)

    if not entendido:
        e["fallos"] = e.get("fallos", 0) + 1
        aviso = {"entidad": "el lugar", "fecha": "el día", "hora": "la hora", "modalidad": "la modalidad",
                 "nombre": "su nombre", "telefono": "el número", "documento": "la cédula",
                 "autorizacion": "si autoriza", "confirmar": "si la confirmo", "corregir": "qué quiere cambiar"}
        dichas.append(_f("calida", f"Perdón, no le entendí {aviso.get(paso, 'bien')}."))
        frases = dichas + _pregunta(ctx, e)
        if e["fallos"] >= 3:
            frases.append(_f("tranquila", "Si prefiere dejarla para después, diga «cancelar»."))
        return Resultado(frases, e)
    e["fallos"] = 0
    return _avanzar(e, ctx, dichas)


def _extraer(texto: str, e: dict, ctx: Contexto, dichas: list[dict], inicio: bool = False) -> None:
    """Toma de una vez lo que la persona adelantó: «quiero una cita presencial en la personería el lunes a las 9»."""
    ent = buscar_entidad(texto, ctx.entidades)
    if ent and ent["id"] != e["entidad_id"]:
        e["entidad_id"], e["entidad"], e["fecha"], e["hora"] = ent["id"], ent["nombre"], None, None
    m = buscar_modalidad(texto)
    if m:
        e["modalidad"] = m
    if not e["entidad_id"]:
        return
    d = buscar_fecha(texto, ctx.hoy, solo_explicita=True)
    if d and d.isoformat() != e["fecha"] and not _aplicar_fecha(ctx, e, d, dichas):
        h, _ = buscar_hora(texto, solo_explicita=True)
        if h:
            e["hora_pedida"] = h
        return
    if e["fecha"]:
        h, franja = buscar_hora(texto, solo_explicita=True)
        if h or (franja and not e["hora"]):
            _aplicar_hora(ctx, e, h, franja, dichas)


def _avanzar(e: dict, ctx: Contexto, dichas: list[dict]) -> Resultado:
    # Si se rechazó un día u hora, la frase de rechazo ya trae la pregunta: no se repite la del paso.
    paso_previo = e.get("paso")
    e["paso"] = _siguiente(e)
    if dichas and dichas[-1]["texto"].endswith("?") and e["paso"] in ("fecha", "hora"):
        return Resultado(dichas, e)
    if e["paso"] != "confirmar":
        nueva = e.get("hora") and f"{e['fecha']} {e['hora']}"
        if nueva and e.get("anotada") != nueva:
            d = date.fromisoformat(e["fecha"])
            lugar = f" en {con_articulo(e['entidad'])}" if paso_previo in (None, "entidad") else ""
            dichas.append(_f("animada", f"¡Anotado! El {fecha_hablada(d)} a {hora_hablada(e['hora'])}{lugar}."))
            e["anotada"] = nueva
        elif paso_previo == "entidad" and e["paso"] != paso_previo and e.get("entidad"):
            dichas.append(_f("animada", f"Listo, en {con_articulo(e['entidad'])}."))
    return Resultado(dichas + _pregunta(ctx, e), e)


def _crear(e: dict, ctx: Contexto) -> Resultado:
    datos = {k: e[k] for k in ("entidad_id", "fecha", "hora", "modalidad", "nombre", "telefono", "documento", "motivo")}
    try:
        fila = ctx.crear(datos)
    except HorarioOcupado:
        e["hora"], e["paso"] = None, "hora"
        return Resultado([_f("seria", "¡Uy! Alguien acaba de tomar ese horario.")] + _pregunta(ctx, e), e)
    d = date.fromisoformat(e["fecha"])
    primer = e["nombre"].split()[0]
    frases = [_f("alegre", f"¡Listo, {primer}! Su cita quedó agendada para el {fecha_hablada(d)} a {hora_hablada(e['hora'])}."),
              _f("animada", f"Es en {con_articulo(e['entidad'])} y es completamente gratuita.")]
    if e["modalidad"] == "presencial":
        frases.append(_f("calida", "Le recomiendo llegar diez minutos antes, con su cédula y los papeles de su caso."))
    else:
        frases.append(_f("calida", "Le contactarán a su celular a esa hora; tenga a mano los papeles de su caso."))
    frases.append(_f("calida", "En la pantalla le dejé los datos de la cita. ¿Le ayudo con algo más?"))
    return Resultado(frases, None, cita=fila)
