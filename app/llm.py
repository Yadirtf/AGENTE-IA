"""Cliente del modelo de lenguaje y de embeddings.

- Chat: Ollama local (por defecto) o cualquier API compatible con OpenAI.
- Embeddings: siempre EmbeddingGemma a través de Ollama (768 dimensiones).
"""
import json
from typing import AsyncIterator

import httpx

from . import config

# EmbeddingGemma rinde mejor con estos prefijos de tarea.
PREFIJO_CONSULTA = "task: search result | query: "
PREFIJO_DOCUMENTO = "title: {titulo} | text: "

_timeout = httpx.Timeout(300.0, connect=5.0)


async def embeber(textos: list[str], tipo: str = "consulta", titulo: str = "none") -> list[list[float]]:
    if tipo == "consulta":
        entradas = [PREFIJO_CONSULTA + t for t in textos]
    else:
        entradas = [PREFIJO_DOCUMENTO.format(titulo=titulo) + t for t in textos]
    async with httpx.AsyncClient(timeout=_timeout) as cli:
        try:
            r = await cli.post(f"{config.OLLAMA_URL}/api/embed",
                               json={"model": config.EMBED_MODELO, "input": entradas, "keep_alive": "60m"})
        except httpx.ConnectError as e:
            raise ErrorOllama(f"No hay conexión con Ollama en {config.OLLAMA_URL}. "
                              "Abra la aplicación Ollama (o ejecute 'ollama serve') y vuelva a intentarlo.") from e
        if r.status_code == 404:
            detalle = _detalle(r)
            if "not found" in detalle.lower() and "model" in detalle.lower():
                raise ErrorOllama(f"Ollama no tiene el modelo '{config.EMBED_MODELO}'. "
                                  f"Ejecute:  ollama pull {config.EMBED_MODELO}   (y verifique con: ollama list)")
            # Ollama antiguo sin /api/embed: se intenta el endpoint anterior, uno por uno
            vectores = []
            for t in entradas:
                r2 = await cli.post(f"{config.OLLAMA_URL}/api/embeddings",
                                    json={"model": config.EMBED_MODELO, "prompt": t})
                if r2.status_code != 200:
                    raise ErrorOllama(
                        f"Ollama respondió {r2.status_code}: {_detalle(r2)}. Su versión de Ollama parece antigua: "
                        f"EmbeddingGemma requiere Ollama 0.11.10 o superior. Actualícelo desde https://ollama.com/download "
                        f"y ejecute: ollama pull {config.EMBED_MODELO}")
                vectores.append(r2.json()["embedding"])
            return vectores
        if r.status_code != 200:
            raise ErrorOllama(f"Ollama respondió {r.status_code} al generar embeddings: {_detalle(r)}")
        return r.json()["embeddings"]


class ErrorOllama(RuntimeError):
    """Error de Ollama con un mensaje claro para el usuario."""


def _detalle(r: httpx.Response) -> str:
    try:
        return r.json().get("error", r.text)
    except Exception:  # noqa: BLE001
        return r.text[:300]


async def chat_stream(mensajes: list[dict], max_tokens: int | None = None,
                      temperatura: float | None = None) -> AsyncIterator[str]:
    """Genera la respuesta token a token."""
    temp = config.LLM_TEMPERATURA if temperatura is None else temperatura
    if config.LLM_PROVEEDOR == "openai":
        async for t in _openai_stream(mensajes, max_tokens, temp):
            yield t
        return
    cuerpo = {
        "model": config.LLM_MODELO,
        "messages": mensajes,
        "stream": True,
        "keep_alive": "60m",
        "options": {"temperature": temp, "num_ctx": config.LLM_CONTEXTO},
    }
    if max_tokens:
        cuerpo["options"]["num_predict"] = max_tokens
    async with httpx.AsyncClient(timeout=_timeout) as cli:
        async with cli.stream("POST", f"{config.OLLAMA_URL}/api/chat", json=cuerpo) as r:
            r.raise_for_status()
            async for linea in r.aiter_lines():
                if not linea:
                    continue
                dato = json.loads(linea)
                trozo = dato.get("message", {}).get("content", "")
                if trozo:
                    yield trozo
                if dato.get("done"):
                    break


async def _openai_stream(mensajes: list[dict], max_tokens: int | None, temp: float) -> AsyncIterator[str]:
    cabeceras = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}
    cuerpo = {"model": config.LLM_MODELO, "messages": mensajes, "stream": True, "temperature": temp}
    if max_tokens:
        cuerpo["max_tokens"] = max_tokens
    async with httpx.AsyncClient(timeout=_timeout) as cli:
        async with cli.stream("POST", f"{config.OPENAI_BASE_URL}/chat/completions",
                              json=cuerpo, headers=cabeceras) as r:
            r.raise_for_status()
            async for linea in r.aiter_lines():
                if not linea.startswith("data:"):
                    continue
                carga = linea[5:].strip()
                if carga == "[DONE]":
                    break
                delta = json.loads(carga)["choices"][0].get("delta", {})
                if delta.get("content"):
                    yield delta["content"]


async def completar(mensajes: list[dict], max_tokens: int | None = None, temperatura: float | None = None) -> str:
    partes = [t async for t in chat_stream(mensajes, max_tokens, temperatura)]
    return "".join(partes)


async def estado() -> dict:
    """Comprueba que Ollama responde y qué modelos tiene descargados."""
    info = {"proveedor": config.LLM_PROVEEDOR, "modelo": config.LLM_MODELO,
            "embeddings": config.EMBED_MODELO, "ollama": False, "modelos": []}
    try:
        async with httpx.AsyncClient(timeout=3) as cli:
            r = await cli.get(f"{config.OLLAMA_URL}/api/tags")
            r.raise_for_status()
            info["ollama"] = True
            info["modelos"] = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    nombres = [m.split(":")[0] for m in info["modelos"]] + info["modelos"]
    info["llm_listo"] = config.LLM_PROVEEDOR == "openai" or config.LLM_MODELO in nombres
    info["embed_listo"] = config.EMBED_MODELO in nombres or f"{config.EMBED_MODELO}:latest" in info["modelos"]
    return info
