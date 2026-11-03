"""Configuración central (variables de entorno / archivo .env)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv es opcional
    pass

RAIZ = Path(__file__).resolve().parent.parent


def _env(nombre: str, defecto: str) -> str:
    return os.getenv(nombre, defecto)


DATABASE_URL = _env("DATABASE_URL", "postgresql://amparo:amparo@localhost:5433/amparo")

# --- LLM -------------------------------------------------------------------
# "ollama" (local, por defecto) u "openai" (cualquier API compatible: Groq,
# Gemini OpenAI-compat, LM Studio, llama.cpp server...)
LLM_PROVEEDOR = _env("LLM_PROVEEDOR", "ollama")
OLLAMA_URL = _env("OLLAMA_URL", "http://localhost:11434")
LLM_MODELO = _env("LLM_MODELO", "qwen2.5:3b")
LLM_CONTEXTO = int(_env("LLM_CONTEXTO", "4096"))
LLM_TEMPERATURA = float(_env("LLM_TEMPERATURA", "0.3"))
OPENAI_BASE_URL = _env("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
OPENAI_API_KEY = _env("OPENAI_API_KEY", "")

# --- Embeddings (EmbeddingGemma vía Ollama, 768 dimensiones) ----------------
EMBED_MODELO = _env("EMBED_MODELO", "embeddinggemma")
EMBED_DIM = 768

# --- RAG ---------------------------------------------------------------------
RAG_K = int(_env("RAG_K", "5"))
RAG_UMBRAL = float(_env("RAG_UMBRAL", "0.30"))

# --- Voz ---------------------------------------------------------------------
WHISPER_MODELO = _env("WHISPER_MODELO", "small")      # tiny | base | small
WHISPER_COMPUTE = _env("WHISPER_COMPUTE", "int8")      # ideal para CPU
_voz = Path(_env("PIPER_VOZ", "modelos/es_MX-claude-high.onnx"))
PIPER_VOZ = str(_voz if _voz.is_absolute() else RAIZ / _voz)
# Carpeta donde viven todas las voces de Piper (.onnx + .onnx.json); PIPER_VOZ es la voz por defecto.
MODELOS = Path(PIPER_VOZ).parent
# Guion hablado: "llm" (Amparo explica con sus palabras y emoción) o "reglas" (más rápido, sin segunda llamada al LLM)
VOZ_GUION = _env("VOZ_GUION", "llm")
