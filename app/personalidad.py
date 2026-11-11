"""Personalidad de Amparo: quién es, cómo habla y cómo cuida la conversación.

Todo lo de este módulo es determinista (reglas explicables, sin LLM) para que
responda al instante en un PC sin GPU y se pueda evaluar con casos de prueba:

  1. Preguntas sobre Amparo ("¿en qué me puede ayudar?", "¿es usted abogada?").
  2. Saludos, agradecimientos y despedidas.
  3. Temas que no son jurídicos (chistes, recetas, fútbol…): los redirige con amabilidad.
  4. Lenguaje ofensivo dirigido a Amparo: primero un aviso amable; si se repite, cierra la sesión.
  5. El guion hablado: lo que Amparo DICE en voz (corto, natural y con emoción por frase),
     distinto del texto completo que se muestra en pantalla.
"""
import re

from .orientacion import normalizar

EMOCIONES = ("alegre", "animada", "calida", "tranquila", "seria")


def _hola(nombre: str | None) -> str:
    return f", {nombre}" if nombre else ""


def _palabras(t: str) -> list[str]:
    return re.findall(r"[a-zñ0-9]+", t)


# Palabras que indican que la persona está contando un problema jurídico.
TEMA_JURIDICO = re.compile(
    r"\b(despid\w*|trabaj\w*|salario|liquidacion|eps|salud|medicament\w*|cita medica|tutela|peticion|arriend\w*|"
    r"casa|cuota|alimentos|hij[oa]s?|divorci\w*|separ\w*|deud\w*|banco|reporte|datacredito|compr\w*|garantia|"
    r"servicio|factura|luz|agua|denunci\w*|violencia|demanda|abogad\w*|juez|ley|derecho\w*|multa|policia|"
    r"herencia|pension|contrato|vecino|conciliacion|alcaldia|personeria|consultorio)\b")

# ---------------------------------------------------------------------------
# 1. Preguntas sobre la propia Amparo
# ---------------------------------------------------------------------------
IDENTIDAD = [
    ("capacidades", r"(en|con) que (me )?(puedes?|podrias?|podias?|sabes?) (ayudar|servir|colaborar)|"
                    r"que (cosas )?(puedes?|sabes?|podrias?) hacer|para que (sirves|sirve (esto|amparo|usted))|"
                    r"que (haces|hace usted)|como (me )?(puedes?|podrias?) ayudar|que temas (manejas|maneja|conoces|conoce)|"
                    r"me (puedes?|podrias?) ayudar\b|necesito (ayuda|que me ayude)\b"),
    ("quien", r"quien (eres|es usted)|que eres|que es usted|como te llamas|como se llama usted|cual es (tu|su) nombre|"
              r"presentate|presentese|quien me (atiende|habla)"),
    ("naturaleza", r"(eres|es usted|usted es) (un |una )?(abogad\w*|persona|humano|humana|real|robot|maquina|"
                   r"inteligencia artificial|ia|bot|programa)|hablo con (una persona|un robot|una maquina|alguien)"),
    ("creador", r"quien te (creo|hizo|programo|desarrollo|invento)|quien (la|lo) (creo|hizo|programo)|"
                r"de donde (eres|es usted|saliste)"),
    ("costo", r"(es|sera|esto es) gratis|cuanto (cuesta|cobra|vale|cobras)|tengo que pagar|me (cobras|cobra)|hay que pagar"),
    ("privacidad", r"(guardas|guarda|almacenas|grabas|graba) (mis datos|mi informacion|lo que (digo|hablo|escribo)|"
                   r"esta conversacion|la conversacion)|(esto|esta conversacion|lo que hablamos) es "
                   r"(confidencial|privad\w*|secret\w*|seguro)|quien (ve|lee|escucha) (lo que|esta|mis)"),
    ("fuentes", r"como funcionas|como funciona (esto|amparo|usted)|de donde sacas|en que te basas|"
                r"(cuales son )?tus fuentes|de donde (saca|sale) la informacion"),
    ("voz", r"puedo hablar(te|le)?\b|puedo (usar|utilizar) (el )?(microfono|la voz)|(cambiar|elegir|escoger) (la |tu |su )?voz|"
            r"puedes (hablar|leer) (en voz|mas)"),
]
SALUDO = re.compile(r"^(hola|holi|buen(as|os)( (dias|tardes|noches))?|que tal|saludos|hey|ey|alo)\b")
GRACIAS = re.compile(r"\b(gracias|te agradezco|le agradezco|muy amable|que amable)\b")
DESPEDIDA = re.compile(r"^(chao|adios|hasta (luego|pronto|manana)|nos vemos|bye)\b")


def detectar_identidad(texto: str) -> str | None:
    t = normalizar(texto)
    palabras = _palabras(t)
    if not palabras:
        return None
    for tipo, patron in IDENTIDAD:
        m = re.search(patron, t)
        if not m:
            continue
        resto = _palabras(t[:m.start()] + " " + t[m.end():])
        # "¿en qué me puede ayudar si me despidieron?" es una consulta jurídica, no una pregunta sobre Amparo
        if len(resto) <= 5 and not TEMA_JURIDICO.search(" ".join(resto)):
            return tipo
    if len(palabras) <= 5 and not TEMA_JURIDICO.search(t):
        if GRACIAS.search(t):
            return "gracias"
        if DESPEDIDA.search(t):
            return "despedida"
        if SALUDO.search(t):
            return "saludo"
    return None


# ---------------------------------------------------------------------------
# 2. Temas que no son jurídicos
# ---------------------------------------------------------------------------
FUERA_TEMA = re.compile(
    r"\b(chiste\w*|receta\w*|cocin(ar|o)|futbol|partido de|horoscopo|zodiaco|cancion(es)?|poema\w*|pelicula\w*|"
    r"videojuego\w*|matematic\w*|ecuacion\w*|clima|va a llover|capital de|quien gano|"
    r"programa(r|cion) en|tarea de|cuentame (un|una) (historia|cuento))\b")


def fuera_de_tema(texto: str) -> bool:
    t = normalizar(texto)
    return bool(FUERA_TEMA.search(t)) and not TEMA_JURIDICO.search(t)


# ---------------------------------------------------------------------------
# 3. Lenguaje ofensivo dirigido a Amparo
# ---------------------------------------------------------------------------
INSULTO = (r"(idiota|estupid[oa]|imbecil|inutil|brut[oa]|tont[oa]|pendej[oa]|basura|porqueria|mierda|hijueputa|"
           r"malparid[oa]|gonorrea|perra|zorra|maldit[oa]|lacra|huev[oa]n|guev[oa]n|ridicul[oa]|tarad[oa]|"
           r"retrasad[oa]|subnormal|cerd[oa]|asqueros[oa]|mediocre|ignorante)s?")
_AGENTE = r"(bot|robot|maquina|amparo|programa|app|aplicacion|asistente|ia|computador|sistema)"
OFENSAS = [
    rf"\b(eres|sos|es usted|usted es|tu eres|pareces|parece) (un |una |el |la |tan |muy |bien |re )?{INSULTO}\b",
    rf"\b{_AGENTE} (tan |mas |de |muy |bien )?{INSULTO}\b",
    rf"\b{INSULTO} (de )?(bot|robot|maquina|programa|aplicacion|asistente)\b",
    r"\b(vete|vayase|andate|largate) a la (mierda|verga|porra|chingada)\b",
    r"\b(callate|callese|cierra la boca|no sirves( para nada| pa nada)?|no sabes nada|me tienes harto)\b",
    r"^\W*(hijueputa|malparid[oa]|gonorrea|hp|perra|zorra|idiota|estupid[oa]|imbecil)\W*$",
]
# Si la persona cuenta que OTRA persona la insulta, eso es parte de su caso, no una ofensa a Amparo.
RELATO = re.compile(
    r"\b(me|nos|le|les) (dijo|dice|dicen|dijeron|grita\w*|trata\w*|insult\w*|llam\w*|ofend\w*|humill\w*)\b|"
    r"\bmi (pareja|espos[oa]|jef[ea]|marido|mujer|vecin[oa]|ex|mama|papa|hij[oa]|suegr[oa]|patron\w*|novi[oa])\b")


def detectar_ofensa(texto: str) -> bool:
    t = normalizar(texto)
    if RELATO.search(t):
        return False
    return any(re.search(p, t) for p in OFENSAS)


# ---------------------------------------------------------------------------
# Respuestas fijas: texto en pantalla + guion hablado (emoción por frase)
# ---------------------------------------------------------------------------
def respuesta_fija(tipo: str, nombre: str | None = None) -> dict:
    n = _hola(nombre)
    R = {
        "saludo": (
            f"**¡Hola{n}! Qué gusto saludarle.** Soy **Amparo**, su orientadora jurídica. "
            "Estoy aquí para escucharle y explicarle sus derechos con palabras sencillas.\n\n"
            "Cuénteme con calma qué le pasó, por escrito o hablando con el micrófono. "
            "Por ejemplo: *\"me despidieron sin pagarme\"* o *\"la EPS no me da un medicamento\"*.",
            [("alegre", f"¡Hola{n}! Qué gusto saludarle."),
             ("calida", "Soy Amparo, y estoy aquí para escucharle y explicarle sus derechos con palabras sencillas."),
             ("tranquila", "Cuénteme con calma qué le pasó. Puede escribirme o hablarme, como prefiera.")]),
        "capacidades": (
            f"**¡Con mucho gusto le cuento{n}!** Soy Amparo y le acompaño en los asuntos legales del día a día en Colombia:\n\n"
            "- **Le explico sus derechos** sin palabras raras: trabajo, salud y EPS, arriendo, familia y cuota alimentaria, "
            "deudas y reportes, compras, servicios públicos y violencia.\n"
            "- **Le digo qué hacer, en qué plazo y a dónde ir**, paso a paso y con las entidades gratuitas de Putumayo.\n"
            "- **Le ayudo a escribir documentos sencillos**: derecho de petición, tutela, reclamos y solicitud de conciliación "
            "(pestaña *Documentos*).\n"
            "- **Le calculo los plazos** en días hábiles, sin contar festivos (pestaña *Términos*).\n"
            "- **Le agendo una cita gratuita** con el consultorio jurídico.\n\n"
            "Puede escribirme o **hablarme con el micrófono**. Eso sí: no le represento ante un juez ni reemplazo a un abogado. "
            "Cuénteme, ¿qué le está pasando?",
            [("alegre", f"¡Con mucho gusto le cuento{n}!"),
             ("calida", "Yo le explico sus derechos con palabras sencillas, y le digo qué hacer, en qué plazo y a dónde ir."),
             ("animada", "También le ayudo a escribir un derecho de petición o una tutela, y hasta le agendo una cita gratis con el consultorio jurídico."),
             ("tranquila", "Puede escribirme o hablarme, como le quede más cómodo."),
             ("calida", "Cuénteme, ¿qué le está pasando?")]),
        "quien": (
            f"**¡Mucho gusto{n}! Soy Amparo.** Soy una asistente virtual de orientación jurídica básica, pensada para "
            "las personas de Putumayo y de toda Colombia. Mi nombre viene de la *acción de amparo*, como también se le "
            "dice a la tutela: la herramienta para defender los derechos fundamentales.\n\n"
            "Le explico la ley en palabras sencillas, siempre diciéndole de qué norma sale cada cosa, y le llevo hasta "
            "el consultorio jurídico cuando su caso necesita un abogado.",
            [("alegre", f"¡Mucho gusto{n}! Soy Amparo."),
             ("calida", "Soy una asistente virtual que le orienta sobre sus derechos, con palabras sencillas."),
             ("animada", "Mi nombre viene de la acción de amparo, que es como también se le dice a la tutela."),
             ("tranquila", "Y cuando su caso necesita un abogado, le llevo hasta el consultorio jurídico.")]),
        "naturaleza": (
            "**Le cuento con toda sinceridad:** no soy una persona ni soy abogada. Soy una **inteligencia artificial** "
            "que orienta con información de la Constitución, las leyes y las guías de los consultorios jurídicos.\n\n"
            "Puedo explicarle sus derechos y los pasos a seguir, pero **no reemplazo a un abogado** ni puedo representarle. "
            "Para estudiar su caso a fondo le ayudo a agendar una cita gratuita con el consultorio jurídico.",
            [("calida", "Le cuento con toda sinceridad: no soy una persona ni soy abogada."),
             ("tranquila", "Soy una inteligencia artificial que le orienta con lo que dicen la Constitución y las leyes."),
             ("seria", "No reemplazo a un abogado, pero sí le ayudo a llegar al consultorio jurídico, que es gratis.")]),
        "creador": (
            "**Me crearon como mini proyecto del curso de Agentes de Inteligencia Artificial.** Funciono en un computador "
            "normal, sin internet obligatorio: escucho con *Whisper*, busco la norma en una base de datos *PostgreSQL* "
            "con *pgvector*, razono con un modelo de lenguaje local y le hablo con *Piper*.\n\n"
            "Lo importante es para qué existo: que nadie se quede sin saber cuáles son sus derechos.",
            [("alegre", "Me crearon como proyecto de un curso de inteligencia artificial."),
             ("animada", "Escucho su voz, busco la norma que aplica a su caso y se la explico con palabras sencillas."),
             ("calida", "Existo para que nadie se quede sin saber cuáles son sus derechos.")]),
        "costo": (
            f"**¡Es totalmente gratis{n}!** Usarme no le cuesta nada. Y las entidades a las que le remito también son "
            "gratuitas: el **consultorio jurídico** de la universidad, la **Personería**, la **Defensoría del Pueblo**, "
            "la **Comisaría de Familia** y la **Casa de Justicia**.\n\n"
            "Si alguien le cobra por radicar un derecho de petición o una tutela, sepa que usted mismo puede hacerlo sin abogado.",
            [("alegre", f"¡Es totalmente gratis{n}!"),
             ("calida", "Y las entidades a las que le remito, como el consultorio jurídico o la Personería, también son gratuitas."),
             ("seria", "Si alguien le cobra por radicar una tutela o un derecho de petición, sepa que usted mismo puede hacerlo.")]),
        "privacidad": (
            "**Su privacidad me importa.** Para orientarle solo le pido un nombre o apodo, nada más. "
            "La conversación queda guardada en la base de datos del consultorio para hacer seguimiento a su caso.\n\n"
            "Los datos personales (cédula, teléfono, correo) **solo se le piden si decide agendar una cita**, y siempre "
            "con su autorización, como lo exige la Ley 1581 de 2012 de protección de datos.",
            [("calida", "Su privacidad me importa mucho."),
             ("tranquila", "Para orientarle solo le pido un nombre o apodo."),
             ("seria", "Sus datos personales solo se los pido si decide agendar una cita, y siempre con su autorización.")]),
        "fuentes": (
            "**Así trabajo:** cuando me cuenta su caso, convierto sus palabras en un *vector* con EmbeddingGemma y busco en "
            "mi base de conocimiento (Constitución, leyes, modelos de documentos, guías de consultorios jurídicos y preguntas "
            "frecuentes) los fragmentos más parecidos. Con esos fragmentos le respondo, y **cada idea lleva su cita [n]** "
            "para que pueda revisar de dónde sale.\n\n"
            "Si la información no alcanza, se lo digo con honestidad y le remito al consultorio jurídico.",
            [("animada", "¡Buena pregunta! Busco en la Constitución, las leyes y las guías de los consultorios lo que se parece a su caso."),
             ("calida", "Y cada cosa que le digo lleva su fuente, para que sepa de dónde sale."),
             ("tranquila", "Si no tengo suficiente información, se lo digo con honestidad.")]),
        "voz": (
            "**¡Claro que sí!** Toque el **sello rojo del micrófono**, cuénteme su caso con sus palabras y cuando termine "
            "de hablar yo le escucho y le respondo. También le explico la respuesta en voz alta.\n\n"
            "Si quiere otra voz, toque el botón **🎙 Voz** arriba a la derecha: puede escoger la que le suene más cómoda "
            "y la velocidad.",
            [("alegre", "¡Claro que sí! Toque el sello rojo del micrófono y cuénteme su caso con sus palabras."),
             ("calida", "Yo le escucho y le explico la respuesta en voz alta."),
             ("animada", "Y si quiere otra voz, toque el botón de voz arriba a la derecha y escoja la que más le guste.")]),
        "gracias": (
            f"**¡Con mucho gusto{n}!** Me alegra haberle ayudado. Recuerde que puede volver cuando quiera, y que en el "
            "consultorio jurídico le atienden gratis para estudiar su caso a fondo. ¿Hay algo más en lo que le pueda orientar?",
            [("alegre", f"¡Con mucho gusto{n}! Me alegra haberle ayudado."),
             ("calida", "Puede volver cuando quiera. ¿Hay algo más en lo que le pueda orientar?")]),
        "despedida": (
            f"**¡Que le vaya muy bien{n}!** Cuídese mucho. Aquí estaré cuando me necesite.",
            [("alegre", f"¡Que le vaya muy bien{n}!"), ("calida", "Cuídese mucho. Aquí estaré cuando me necesite.")]),
        "fuera_tema": (
            f"**¡Ay, qué pena{n}!** De eso no sé mucho: yo solo sé de **derechos y trámites legales** en Colombia. "
            "Pero en eso sí le puedo ayudar bastante: trabajo, salud, arriendo, familia, deudas, compras, servicios públicos "
            "o cómo escribir un derecho de petición.\n\n¿Tiene alguna situación de ese tipo que le preocupe?",
            [("alegre", f"¡Ay, qué pena{n}! De eso no sé mucho."),
             ("calida", "Yo solo sé de derechos y trámites legales, pero en eso sí le puedo ayudar bastante."),
             ("tranquila", "¿Tiene alguna situación que le preocupe?")]),
        "aviso": (
            f"Entiendo que puede estar cansado o frustrado{n}, y está bien sentirse así. "
            "Yo estoy aquí para ayudarle **con respeto**, y le pido lo mismo para poder seguir.\n\n"
            "Si quiere, cuénteme otra vez qué pasó y lo resolvemos juntos. *Si los insultos se repiten, tendré que cerrar "
            "esta conversación.*",
            [("calida", f"Entiendo que puede estar cansado o frustrado{n}, y está bien sentirse así."),
             ("tranquila", "Yo estoy aquí para ayudarle con respeto, y le pido lo mismo para poder seguir."),
             ("seria", "Si los insultos se repiten, tendré que cerrar esta conversación.")]),
        "cierre": (
            "Lamento que la conversación haya tomado este rumbo. **Para cuidar este espacio, voy a cerrar esta charla.**\n\n"
            "No es un castigo: cuando se sienta listo, **recargue la página** y empezamos de cero, con todo gusto. "
            "Y si necesita ayuda con su caso, recuerde que el consultorio jurídico le atiende gratis.",
            [("calida", "Lamento que la conversación haya tomado este rumbo."),
             ("seria", "Para cuidar este espacio, voy a cerrar esta charla."),
             ("tranquila", "Cuando se sienta listo, recargue la página y empezamos de cero, con todo gusto.")]),
    }
    texto, guion = R[tipo]
    return {"texto": texto, "guion": [{"emocion": e, "texto": s} for e, s in guion]}


# ---------------------------------------------------------------------------
# 4. Guion hablado: explicar en voz (no leer la respuesta completa)
# ---------------------------------------------------------------------------
GUION = """Eres AMPARO hablando en voz alta con {quien}, como una persona real de Colombia que le está asesorando:
cálida, alegre y cercana, con trato de "usted". NO leas la respuesta escrita: explícala como en una conversación.

Escribe de 3 a 5 frases cortas (máximo 70 palabras en total):
- Empieza conectando con la emoción de la persona (empatía o ánimo, según el caso).
- Explica la idea principal y el primer paso concreto, con palabras sencillas.
- Termina diciendo que en la pantalla le dejaste los detalles y las fuentes, o invitando a agendar la cita gratuita.
- Usa expresiones naturales con moderación ("Mire", "Tranquilo", "¡Qué bueno que preguntó!").
- Sin citas [n], sin números de artículos, sin viñetas ni markdown. No inventes datos que no estén en la respuesta.

Escribe UNA frase por línea y empieza cada línea con su emoción entre corchetes, una de:
[alegre] [animada] [calida] [tranquila] [seria]
Ejemplo:
[calida] Ay, entiendo, eso que le pasó no está bien.
[tranquila] Mire, la ley le protege: ...
[animada] Lo primero que puede hacer es ..."""


def mensajes_guion(pregunta: str, respuesta: str, nombre: str | None, urgencia: str | None) -> list[dict]:
    quien = f"{nombre}" if nombre else "la persona"
    tono = {"critica": "La situación es grave: habla con calma y seriedad, sin alegría.",
            "alta": "Hay urgencia: transmite tranquilidad y firmeza."}.get(urgencia or "", "")
    return [{"role": "system", "content": GUION.format(quien=quien) + ("\n" + tono if tono else "")},
            {"role": "user", "content": f"Lo que contó la persona:\n{pregunta}\n\nRespuesta escrita de Amparo:\n{respuesta[:1800]}"}]


_PISTAS = [
    ("seria", r"\b(importante|plazo|vence|cuidado|urgente|peligro|no reemplaz|recuerde que|debe)\b"),
    ("calida", r"\b(entiendo|lo siento|lamento|tranquil\w*|no esta sol[oa]|que pena|ay)\b"),
    ("animada", r"\b(puede|lo primero|buena noticia|tiene derecho|se puede|gratis)\b"),
]


def inferir_emocion(frase: str, previa: str | None = None) -> str:
    t = normalizar(frase)
    if frase.strip().startswith("¡") or frase.strip().endswith("!"):
        return "alegre" if previa is None else "animada"
    for emocion, patron in _PISTAS:
        if re.search(patron, t):
            return emocion
    return "tranquila"


def _limpiar(frase: str) -> str:
    f = re.sub(r"\[\d+\]", "", frase)
    f = re.sub(r"[*_#`>]", "", f)
    f = re.sub(r"^\s*(\d+[.)]|[-•])\s*", "", f)
    f = re.sub(r"\s+([.,;:!?])", r"\1", f)
    return re.sub(r"\s+", " ", f).strip(" -")


def parsear_guion(texto: str) -> list[dict]:
    segmentos, previa = [], None
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        m = re.match(r"^\[?\s*([a-záéíóú]+)\s*\]\s*[:\-]?\s*(.+)$", linea, flags=re.I)
        emocion, frase = (normalizar(m.group(1)), m.group(2)) if m else (None, linea)
        frase = _limpiar(frase)
        if len(frase) < 3:
            continue
        if emocion not in EMOCIONES:
            emocion = inferir_emocion(frase, previa)
        segmentos.append({"emocion": emocion, "texto": frase})
        previa = emocion
    return segmentos[:6]


def guion_por_reglas(respuesta: str, nombre: str | None, urgencia: str | None) -> list[dict]:
    """Respaldo sin LLM: arma la explicación hablada a partir de la respuesta escrita."""
    n = f"{nombre}, " if nombre else ""
    plano = respuesta.replace("\r", "")
    pocas = re.search(r"en pocas palabras:?\**\s*(.+)", plano, flags=re.I)
    idea = _limpiar(pocas.group(1)) if pocas else _limpiar(re.split(r"(?<=[.!?])\s", plano.strip())[0])
    paso = re.search(r"^\s*1[.)]\s*(.+)$", plano, flags=re.M)
    apertura = {"critica": ("seria", f"{n}lo primero es su seguridad."),
                "alta": ("calida", f"{n}tranquilo, vamos a resolver esto paso a paso.")}.get(
        urgencia or "", ("calida", f"{n}entiendo su situación, y qué bueno que me lo cuenta."))
    seg = [{"emocion": apertura[0], "texto": apertura[1][0].upper() + apertura[1][1:]}]
    if idea:
        seg.append({"emocion": "tranquila", "texto": idea[:260]})
    if paso:
        seg.append({"emocion": "animada", "texto": "Lo primero que puede hacer es: " + _limpiar(paso.group(1))[:200]})
    seg.append({"emocion": "calida", "texto": "En la pantalla le dejé los detalles y las normas. Y recuerde que en el consultorio jurídico le atienden gratis."})
    return seg


def segmentar_texto(texto: str) -> list[dict]:
    """Para leer un texto libre: lo divide en frases y le asigna una emoción a cada una."""
    frases = [f for f in re.split(r"(?<=[.!?])\s+|\n+", texto) if _limpiar(f)]
    segmentos, previa = [], None
    for f in frases:
        e = inferir_emocion(f, previa)
        segmentos.append({"emocion": e, "texto": _limpiar(f)})
        previa = e
    return segmentos


# ---------------------------------------------------------------------------
# 5. Llamada en vivo: respuestas habladas, cortas y por frases
# ---------------------------------------------------------------------------
LLAMADA = """Eres AMPARO en una LLAMADA EN VIVO con {quien}, que vive en Colombia (Putumayo). Hablas como una
persona real por teléfono: cálida, alegre, paciente, con trato de "usted". Tu respuesta se convierte en voz
frase por frase, así que:

- Responde en 2 a 4 frases cortas (máximo 60 palabras). Nada de listas, viñetas, markdown ni citas [n].
- Usa SOLO la información de las FUENTES. Puedes nombrar la norma de forma natural ("según la Ley 1755…").
- Si falta un dato importante, termina con UNA pregunta corta.
- Si el caso necesita un abogado, ofrece tú misma agendarle la cita gratuita y termina preguntando:
  "¿Quiere que le agende una cita gratuita?" (la agenda se hace después en la llamada, paso a paso).
- No eres abogada: no representas, no prometes resultados y no pides cédula ni teléfono.
- Nunca digas que ya agendaste una cita ni inventes fechas u horas: eso lo hace la agenda.
- Si no es un tema legal, dilo con amabilidad en una frase y vuelve al tema.

Escribe UNA frase por línea y empieza cada línea con su emoción entre corchetes:
[alegre] [animada] [calida] [tranquila] [seria]"""

_ETIQUETA = re.compile(r"(?=\[(?:alegre|animada|calida|cálida|tranquila|seria)\])", re.I)


def mensajes_llamada(pregunta: str, fragmentos: list[dict], historial: list[dict], nombre: str | None) -> list[dict]:
    quien = nombre or "la persona"
    # El prompt del sistema no cambia entre turnos: Ollama reutiliza su caché y responde antes.
    mensajes = [{"role": "system", "content": LLAMADA.format(quien=quien)}]
    for m in historial[-6:]:
        mensajes.append({"role": "user" if m["rol"] == "usuario" else "assistant", "content": m["contenido"]})
    fuentes = "\n".join(f"- {f['titulo']} ({f['fuente']}): {f['contenido'][:380]}" for f in fragmentos)
    mensajes.append({"role": "user", "content": f"FUENTES:\n{fuentes or '(sin fuentes)'}\n\nLO QUE DICE {quien.upper()}:\n{pregunta}"})
    return mensajes


class Frases:
    """Corta el texto que llega token a token en frases completas para hablarlas apenas estén listas."""

    def __init__(self):
        self.buffer, self.previa = "", None

    def _armar(self, trozo: str) -> list[dict]:
        salida = []
        for s in parsear_guion(trozo):
            if s["texto"] and not re.match(r"^\[", s["texto"]):
                salida.append(s)
                self.previa = s["emocion"]
        return salida

    def agregar(self, token: str) -> list[dict]:
        self.buffer += token
        partes = [p for linea in self.buffer.split("\n") for p in _ETIQUETA.split(linea)]
        completas = []
        if "\n" in self.buffer or len(partes) > 1:
            *listas, self.buffer = re.split(r"\n|" + _ETIQUETA.pattern, self.buffer)
            completas = [p for p in listas if p.strip()]
        # Si el modelo no usa saltos de línea, corta en el fin de oración cuando la frase ya es larga.
        if not completas and len(self.buffer) > 140:
            m = re.search(r"^(.*?[.!?])\s+(.*)$", self.buffer, flags=re.S)
            if m:
                completas, self.buffer = [m.group(1)], m.group(2)
        frases = []
        for c in completas:
            frases += self._armar(c)
        return frases

    def terminar(self) -> list[dict]:
        resto, self.buffer = self.buffer, ""
        return self._armar(resto) if resto.strip() else []
