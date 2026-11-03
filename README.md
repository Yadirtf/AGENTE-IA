# Amparo · Agente de orientación jurídica básica

**UniPutumayo · Agentes de IA.** Este agente conversacional le explica a una persona sus derechos según la ley colombiana. Le dice **qué hacer**, **en qué plazo** y **a dónde acudir**, y cita la norma de donde sale cada afirmación. Puede usarse por texto o por voz.

```
voz ─▶ Whisper (STT) ─▶ EmbeddingGemma ─▶ PostgreSQL + pgvector ─▶ LLM (Ollama) ─▶ respuesta ─▶ Piper (TTS)
                                         (búsqueda híbrida RRF)     (streaming)      + citas      + voz
```

Todo corre **localmente en CPU**. Está pensado para un PC de **16 GB de RAM sin tarjeta gráfica NVIDIA**.

---

## Qué lo hace distinto

| Función | Descripción |
|---|---|
| **Expediente vivo** | Cada consulta abre un expediente con número propio. El agente clasifica el área jurídica y la marca con un sello animado. También muestra un *diagnóstico* con la probabilidad de cada área, un **semáforo de urgencia**, la **ruta de acción** paso a paso y las entidades gratuitas donde acudir. |
| **Citas verificables** | Las respuestas citan `[1] [2]`. Al pasar el cursor sobre una cita se resalta el fragmento de ley recuperado, junto con su similitud semántica. |
| **Tubería en vivo** | Debajo del chat se ve cada etapa (Voz → Whisper → Gemma → pgvector → LLM → Piper) y cuántos milisegundos tardó. |
| **Voz con sello de lacre** | Se toca el sello para hablar. Una onda circular reacciona al micrófono y la grabación se corta sola tras 1,8 s de silencio. Cuando el agente responde en voz alta, la onda se pone verde. |
| **Detección de emergencias** | Antes de llamar al LLM se revisa si el mensaje habla de violencia, riesgo de suicidio o abuso de menores. Si es así, aparece una franja con las líneas **123, 155, 141 y 122**, que se pueden marcar con un toque. |
| **Taller de documentos** | Genera un derecho de petición, una tutela, un reclamo por garantía, un reclamo de habeas data, un preaviso de arriendo o una solicitud de conciliación (cada documento impreso se registra en el caso), con vista previa en hoja A4. El botón **Redactar hechos con IA** reescribe el relato en lenguaje formal, y el documento se puede imprimir o guardar como PDF. |
| **Calculadora de términos** | Cuenta días hábiles descontando los festivos de Colombia (Ley 51 de 1983, festivos móviles y de Pascua) y muestra un calendario con el día de vencimiento. |
| **Directorio** | Entidades gratuitas de Mocoa/Putumayo y nacionales, filtradas por área (están guardadas en PostgreSQL). |
| **Laboratorio** | Muestra la arquitectura, la latencia promedio de cada etapa, las consultas por área y una **evaluación con 28 casos de prueba** (exactitud del área, Hit@3, Hit@5, MRR, detección de emergencias, detección de límites y cobertura de la respuesta). |
| **Casos** | Tablero por estado (abierto → orientado → remitido → en trámite → cerrado). Las carpetas se arrastran entre columnas y cada cambio queda en `historial_estados`. Incluye la agenda de citas con el consultorio. |
| **Consultantes y citas** | Los datos del consultante se toman al agendar la cita, con autorización de datos (Ley 1581 de 2012). Cada respuesta termina con una **remisión al consultorio jurídico** y un botón para agendar cita: se elige la entidad, uno de los próximos días hábiles (sin festivos) y una hora libre, y se genera una constancia imprimible. El caso pasa a «Remitido». |
| **Límites del agente** | Detecta pedidos fuera de alcance (representarle, redactar demandas, predecir fallos, evadir la ley), los marca en la respuesta y remite al consultorio. Se evalúa con casos de prueba propios. |
| **Personalidad propia** | Amparo es cálida y alegre: pregunta al inicio *cómo le gusta que le llamen* (solo un nombre o apodo) y saluda por ese nombre. Responde al instante, sin LLM, las preguntas sobre ella misma (*¿en qué me puedes ayudar?, ¿eres abogada?, ¿es gratis?, ¿guardas mis datos?, ¿de dónde sacas la información?*), los saludos y las despedidas. Si le preguntan algo que no es jurídico, lo dice con amabilidad y vuelve al tema. |
| **Explica en voz, no lee** | La voz no lee el texto de la pantalla. Después de cada respuesta el LLM escribe un **guion hablado** de 3 a 5 frases cortas, como lo diría una persona, con una emoción por frase (*alegre, animada, cálida, tranquila, seria*). Piper ajusta el ritmo, la variación y el tono de cada frase, y la interfaz muestra la nota de voz con subtítulos que se resaltan mientras habla. |
| **📞 Llamada en vivo** | Una pestaña para conversar con Amparo como en una llamada, sin tocar botones. El micrófono detecta solo cuándo empieza y termina usted de hablar (umbral que se adapta al ruido del cuarto y guarda ~350 ms previos para no cortar la primera sílaba). Whisper `base` transcribe el turno y `/api/llamada` responde **por frases**: la voz empieza con la primera frase mientras el LLM escribe la siguiente. Si tarda, Amparo dice *"Mmm, a ver…"* como una persona. **Si usted habla mientras ella habla, se calla al instante** (se corta el audio, la voz y la petición al LLM) y le escucha. Transcripción en vivo con las fuentes de cada respuesta, tiempos por turno, y al colgar un resumen con botón para agendar la cita. Todo queda en el historial. |
| **Elegir la voz** | El botón **🎙 Voz** muestra las voces de Piper instaladas (México, Argentina y España, femeninas y masculinas) y las del navegador (en Edge, las voces «Natural» suenan muy humanas). Cada una tiene muestra, y se puede ajustar la velocidad. La elección queda guardada en el navegador. |
| **Respeto y cierre de sesión** | Si insultan a Amparo, responde con amabilidad y pide respeto. Si se repite, cierra la charla: el chat queda bloqueado hasta recargar la página y la conversación queda en el historial como «cerrada». Si la persona cuenta que *otra persona* la insulta («mi pareja me dice inútil»), eso se trata como parte de su caso y no se corta. |
| **Historial de charlas** | El botón **🗂** abre todas las charlas guardadas, agrupadas por día, con buscador por nombre o tema. Se pueden reabrir; las cerradas por ofensas se ven en modo lectura. |
| **Identificación en dos pasos** | Al inicio solo se pide un nombre o apodo. La cédula, el teléfono, el correo y la autorización de datos (Ley 1581 de 2012) se piden únicamente al agendar la cita. |
| **Modo sencillo / técnico** y **modo nocturno** | Cambian el nivel del lenguaje jurídico y la paleta de colores. |

---

## Elección de modelos para 16 GB sin GPU

| Componente | Modelo | RAM aprox. | Por qué |
|---|---|---|---|
| LLM | **`qwen2.5:3b`** (Ollama, Q4) | ~2,5 GB | Es de los modelos pequeños que mejor escriben en español. En una CPU moderna genera unos 8–15 tokens/s. |
| Embeddings | **`embeddinggemma`** (300M) | ~0,6 GB | Es el que pide el curso. Produce vectores de 768 dimensiones y es multilingüe. |
| STT | **faster-whisper `small`** int8 | ~0,8 GB | Transcribe bien el español en CPU. Con `base` es el doble de rápido, a cambio de algo de precisión. |
| TTS | **Piper `es_MX-claude-high`** | ~0,1 GB | Voz natural en español que funciona en CPU casi en tiempo real. |
| BD | PostgreSQL 16 + pgvector | ~0,2 GB | Índice HNSW por coseno más búsqueda léxica `tsvector` en español. |

**Total: unos 4–5 GB.** Queda RAM de sobra para el navegador y el sistema.

Alternativas:
- Si quiere más calidad y acepta más lentitud: `gemma3:4b` (~3,3 GB) o `qwen2.5:7b` (~5 GB, 3–6 tokens/s).
- Si quiere más velocidad: `llama3.2:3b` o `qwen2.5:1.5b`.
- **Para la exposición**, si el PC va lento, puede usar una API gratuita compatible con OpenAI, como Groq. Basta con cambiar `LLM_PROVEEDOR=openai` en `.env`. Los embeddings, la base de datos y la voz siguen siendo locales.

---

## Instalación (Windows, macOS o Linux)

Requisitos: **Python 3.11+**, **Docker Desktop** y **[Ollama](https://ollama.com/download) 0.11.10 o superior** (EmbeddingGemma no funciona en versiones anteriores; compruebe con `ollama --version`).

```bash
# 1. Base de datos PostgreSQL + pgvector
docker compose up -d

# 2. Modelos en Ollama
ollama pull qwen2.5:3b
ollama pull embeddinggemma

# 3. Entorno de Python
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env

# 4. Voces en español para Piper
python -m scripts.descargar_voz            # solo la voz por defecto (~110 MB)
python -m scripts.descargar_voz --todas    # las 6 voces del catálogo (~460 MB), para elegir en «🎙 Voz»
python -m scripts.descargar_voz --lista    # ver el catálogo

# 5. Verificar que todo está listo (Ollama, modelos, PostgreSQL, voz)
python -m scripts.diagnostico

# 6. Cargar la base de conocimiento (esquema + catálogos + embeddings)
python -m scripts.ingestar

# 7. Ejecutar
uvicorn app.main:app --port 8000
```

Abra **http://localhost:8000**. El micrófono solo funciona en `localhost` o con HTTPS. En Windows, después de la primera instalación basta con ejecutar `iniciar.bat`.

> La primera vez que use el micrófono, faster-whisper descargará el modelo `small` (~460 MB). Si Piper no está disponible, la interfaz usa automáticamente la voz del navegador. Si Whisper no está disponible, usa el dictado del navegador.

### Problemas frecuentes

| Error | Solución |
|---|---|
| `404 Not Found` en `/api/embed` | Falta el modelo de embeddings: `ollama pull embeddinggemma` y compruebe con `ollama list`. Si ya está, actualice Ollama a 0.11.10 o superior. |
| `Connection refused` en el puerto 11434 | Ollama no está abierto: inicie la aplicación Ollama o ejecute `ollama serve`. |
| `couldn't get a connection` / puerto 5433 | La base de datos no está encendida: abra Docker Desktop y ejecute `docker compose up -d`. |
| El micrófono no funciona | Abra la página como `http://localhost:8000` (no con la IP) y permita el micrófono en el navegador. |
| En la llamada, Amparo se interrumpe sola | Su voz por los parlantes llega al micrófono. Use audífonos o baje el volumen; también puede pulsar *Espacio* para interrumpirla a mano. |
| La llamada responde lento | Use `WHISPER_LLAMADA=tiny` en `.env`, cierre otros programas pesados o use la API (Groq) para el LLM. La primera llamada descarga Whisper `base` (~145 MB). |

### Evaluación

```bash
python -m scripts.evaluar            # recuperación y clasificación (segundos)
python -m scripts.evaluar --con-llm  # además mide la cobertura de la respuesta del LLM
```

También se puede ejecutar desde la pestaña **Laboratorio**. Los resultados quedan guardados en la tabla `evaluaciones`.

---

## Estructura

```
app/
  main.py          API FastAPI y streaming SSE de la consulta
  llm.py           Ollama / API compatible OpenAI + EmbeddingGemma
  rag.py           Búsqueda híbrida pgvector + tsvector con Reciprocal Rank Fusion
  orientacion.py   Emergencias, urgencia, clasificación de área y prompt
  personalidad.py  Preguntas sobre Amparo, ofensas, temas no jurídicos y guion hablado con emoción
  voz.py           faster-whisper (STT) y Piper (TTS) con varias voces y prosodia por frase
  evaluacion.py    Métricas con casos de prueba
sql/
  schema.sql       Tablas: catálogos, conocimiento vectorial, conversaciones y trazabilidad
  seed.sql         Áreas, rutas de acción y directorio de entidades
conocimiento/      17 documentos: Constitución (artículos clave), normas básicas, modelos de
                   petición y tutela, guía de consultorios jurídicos y preguntas frecuentes
eval/casos.json    28 casos de prueba con área, fuente y límite esperados
eval/personalidad.json  26 casos: preguntas sobre Amparo, temas no jurídicos y ofensas (y relatos que NO son ofensas)
scripts/           ingestar.py · evaluar.py · descargar_voz.py
web/               Interfaz: index.html · estilos.css · app.js · llamada.js · terminos.js · plantillas.js
```

### Modelo de datos

- **Conocimiento (vectorial):** `documentos` → `fragmentos` (`embedding vector(768)` con índice HNSW, más `tsv` generado en español).
- **Dominio:** `areas` (con embedding para clasificar), `rutas`, `entidades`.
- **Transaccional:** `consultantes` (con consentimiento de datos), `conversaciones` = **casos** (tipo de consulta, urgencia, **estado**, consultante), `historial_estados`, `citas_consultorio` (sin choques de horario por índice único), `documentos_generados`, y la vista `casos` para informes.
- **Trazabilidad:** `mensajes` (fuentes, expediente, remisión, **guion hablado**, tipo de respuesta y métricas de latencia en JSONB) y `evaluaciones`.
- **Sesión:** `conversaciones.alias` (nombre o apodo), `advertencias`, `bloqueada` y `motivo_cierre`.

| Requisito del punto 15 | Dónde está |
|---|---|
| Consultantes | tabla `consultantes` · ficha en el expediente |
| Casos y estado de cada caso | `conversaciones.estado` + `historial_estados` + vista `casos` · pestaña **Casos** |
| Tipo de consulta | `conversaciones.area` (clasificada con embeddings) |
| Documentos generados | `documentos_generados` · pestaña **Documentos** |
| Citas con el consultorio jurídico | `citas_consultorio` · botón de remisión y agenda |
| Constitución, normas, modelos, guías, FAQ | `conocimiento/14`–`17` y `01`–`13`, vectorizados en `fragmentos` |
| No reemplaza a un abogado y remite al consultorio | remisión fija al final de cada respuesta + detección de límites |

### Cómo responde

1. **Seguridad.** Unas reglas detectan emergencias antes de cualquier llamada al modelo.
1. **Personalidad.** Si no hay emergencia, se revisa si es una ofensa (aviso o cierre), una pregunta sobre Amparo, un saludo o un tema no jurídico. Esas respuestas son fijas e instantáneas, y no abren expediente.
2. **Embedding.** EmbeddingGemma vectoriza la pregunta con el prefijo de tarea `task: search result | query:`. Si es una pregunta de seguimiento corta, se combina con la anterior.
3. **Recuperación híbrida.** Se toman los 30 mejores por coseno en pgvector y los 30 mejores por `ts_rank` en español, y se fusionan con RRF (k=60).
4. **Expediente.** El área se calcula por similitud con los embeddings de cada área más los votos de los fragmentos recuperados. Luego se asignan urgencia, ruta y entidades.
5. **Generación.** El prompt obliga a usar solo las fuentes, citar `[n]`, no inventar artículos y seguir un formato fijo (*En pocas palabras · Lo que dice la norma · Qué puede hacer · A dónde acudir*).
6. **Llamada en vivo.** En la pestaña Llamada el turno usa un prompt corto (2 a 4 frases, sin markdown), 3 fragmentos recortados y un prompt de sistema fijo para que Ollama reutilice su caché. Si la persona interrumpe, el navegador cancela la petición y lo que Amparo alcanzó a decir se guarda marcado como *(interrumpida)*.
6. **Guion hablado.** Una segunda llamada corta al LLM (máx. 180 tokens) convierte la respuesta en lo que Amparo dirá en voz, con una emoción por frase. Si el LLM falla, se arma por reglas. Con `VOZ_GUION=reglas` en `.env` se omite esa llamada (más rápido en PCs lentos).
6. **Remisión.** Al final de cada respuesta el sistema añade (sin depender del LLM) el recordatorio de que Amparo no reemplaza a un abogado y la opción de agendar cita con el consultorio jurídico.
7. **Trazabilidad.** Todo se guarda en PostgreSQL con sus tiempos, y el caso pasa de «abierto» a «orientado».

---

## Guion sugerido para la presentación (6 min)

1. **Inicio.** Al abrir, Amparo pregunta *¿cómo le gusta que le llame?*; escriba un nombre y escuche el saludo. Muestre la portada y las fichas de ejemplo. Señale los indicadores de estado (LLM, embeddings, pgvector, Whisper, Piper).
2. **Voz.** Toque el sello y diga *"La EPS no me quiere entregar un medicamento que me ordenó el médico"*. Muestre cómo se iluminan las etapas de la tubería, el sello de urgencia en el expediente, la ruta de acción y las citas enlazadas a las fuentes con su similitud.
3. **Seguimiento.** Pregunte *"¿y si no me responden?"* para mostrar la memoria conversacional. Señale que la voz *explica* (nota de voz con subtítulos) en lugar de leer todo.
3. **Personalidad.** Pregunte *"¿en qué me puedes ayudar?"* y *"¿eres abogada?"*. Abra **🎙 Voz**, pruebe dos voces y cambie la velocidad.
4. **Documento.** Pulse **Convertir en documento**. Se sugiere la tutela; luego pulse **Redactar hechos con IA** e **Imprimir**.
5. **Términos.** Calcule los 15 días hábiles de un derecho de petición y muestre que el calendario salta los festivos.
6. **Seguridad.** Escriba *"mi pareja me pega"* y muestre la franja de emergencia.
7. **Límites y remisión.** Pregunte *"¿usted me puede representar en la audiencia?"*: aparece el aviso de límite. Pulse **Agendar cita con el consultorio jurídico**, elija día y hora y muestre la constancia. En **Casos**, el expediente ya está en «Remitido»; arrástrelo a «En trámite».
8. **📞 Llamada en vivo.** Abra la pestaña **Llamada**, toque el teléfono verde y converse sin tocar nada. Mientras Amparo explica, interrúmpala con *"espere, ¿y si no me responden?"*: se calla y le responde a la nueva pregunta. Cuelgue y muestre el resumen.
8. **Respeto.** Escriba *"eres una inútil"* (aviso amable) y luego *"bot estúpido"* (cierre de la sesión). Recargue la página y abra el **🗂 historial**: la charla aparece como «cerrada».
8. **Laboratorio.** Ejecute la evaluación y explique Hit@k, MRR, la exactitud por área y el dial de **Personalidad**.

---

## Aviso

Amparo **orienta, no reemplaza a un abogado**. La información de `conocimiento/` resume normas colombianas vigentes a 2026 y debe verificarse en las fuentes oficiales, cuyo enlace está en cada documento. Los datos del directorio son de referencia: confirme direcciones y horarios en los canales oficiales.
