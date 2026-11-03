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
| **Taller de documentos** | Genera un derecho de petición, una tutela, un reclamo por garantía, un reclamo de habeas data o un preaviso de arriendo, con vista previa en hoja A4. El botón **Redactar hechos con IA** reescribe el relato en lenguaje formal, y el documento se puede imprimir o guardar como PDF. |
| **Calculadora de términos** | Cuenta días hábiles descontando los festivos de Colombia (Ley 51 de 1983, festivos móviles y de Pascua) y muestra un calendario con el día de vencimiento. |
| **Directorio** | Entidades gratuitas de Mocoa/Putumayo y nacionales, filtradas por área (están guardadas en PostgreSQL). |
| **Laboratorio** | Muestra la arquitectura, la latencia promedio de cada etapa, las consultas por área y una **evaluación con 21 casos de prueba** (exactitud del área, Hit@3, Hit@5, MRR, detección de emergencias y cobertura de la respuesta). |
| **Archivo** | Historial de consultas guardado en PostgreSQL, que se puede retomar en cualquier momento. |
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

Requisitos: **Python 3.11+**, **Docker Desktop** y **[Ollama](https://ollama.com/download)**.

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

# 4. Voz en español para Piper (~110 MB)
python -m scripts.descargar_voz

# 5. Cargar la base de conocimiento (esquema + catálogos + embeddings)
python -m scripts.ingestar

# 6. Ejecutar
uvicorn app.main:app --port 8000
```

Abra **http://localhost:8000**. El micrófono solo funciona en `localhost` o con HTTPS. En Windows, después de la primera instalación basta con ejecutar `iniciar.bat`.

> La primera vez que use el micrófono, faster-whisper descargará el modelo `small` (~460 MB). Si Piper no está disponible, la interfaz usa automáticamente la voz del navegador. Si Whisper no está disponible, usa el dictado del navegador.

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
  voz.py           faster-whisper (STT) y Piper (TTS)
  evaluacion.py    Métricas con casos de prueba
sql/
  schema.sql       Tablas: catálogos, conocimiento vectorial, conversaciones y trazabilidad
  seed.sql         Áreas, rutas de acción y directorio de entidades
conocimiento/      13 documentos de derecho colombiano (Markdown con metadatos)
eval/casos.json    21 casos de prueba con área y fuente esperadas
scripts/           ingestar.py · evaluar.py · descargar_voz.py
web/               Interfaz: index.html · estilos.css · app.js · terminos.js · plantillas.js
```

### Modelo de datos

- **Conocimiento (vectorial):** `documentos` → `fragmentos` (`embedding vector(768)` con índice HNSW, más `tsv` generado en español).
- **Dominio:** `areas` (con embedding para clasificar), `rutas`, `entidades`.
- **Transaccional y trazabilidad:** `conversaciones` → `mensajes` (fuentes, expediente y métricas de latencia en JSONB), `documentos_generados`, `evaluaciones`.

### Cómo responde

1. **Seguridad.** Unas reglas detectan emergencias antes de cualquier llamada al modelo.
2. **Embedding.** EmbeddingGemma vectoriza la pregunta con el prefijo de tarea `task: search result | query:`. Si es una pregunta de seguimiento corta, se combina con la anterior.
3. **Recuperación híbrida.** Se toman los 30 mejores por coseno en pgvector y los 30 mejores por `ts_rank` en español, y se fusionan con RRF (k=60).
4. **Expediente.** El área se calcula por similitud con los embeddings de cada área más los votos de los fragmentos recuperados. Luego se asignan urgencia, ruta y entidades.
5. **Generación.** El prompt obliga a usar solo las fuentes, citar `[n]`, no inventar artículos y seguir un formato fijo (*En pocas palabras · Lo que dice la norma · Qué puede hacer · A dónde acudir*).
6. **Trazabilidad.** Todo se guarda en PostgreSQL con sus tiempos.

---

## Guion sugerido para la presentación (5 min)

1. **Inicio.** Muestre la portada y las fichas de ejemplo. Señale los indicadores de estado (LLM, embeddings, pgvector, Whisper, Piper).
2. **Voz.** Toque el sello y diga *"La EPS no me quiere entregar un medicamento que me ordenó el médico"*. Muestre cómo se iluminan las etapas de la tubería, el sello de urgencia en el expediente, la ruta de acción y las citas enlazadas a las fuentes con su similitud.
3. **Seguimiento.** Pregunte *"¿y si no me responden?"* para mostrar la memoria conversacional.
4. **Documento.** Pulse **Convertir en documento**. Se sugiere la tutela; luego pulse **Redactar hechos con IA** e **Imprimir**.
5. **Términos.** Calcule los 15 días hábiles de un derecho de petición y muestre que el calendario salta los festivos.
6. **Seguridad.** Escriba *"mi pareja me pega"* y muestre la franja de emergencia.
7. **Laboratorio.** Ejecute la evaluación y explique Hit@k, MRR y la exactitud por área.

---

## Aviso

Amparo **orienta, no reemplaza a un abogado**. La información de `conocimiento/` resume normas colombianas vigentes a 2026 y debe verificarse en las fuentes oficiales, cuyo enlace está en cada documento. Los datos del directorio son de referencia: confirme direcciones y horarios en los canales oficiales.
