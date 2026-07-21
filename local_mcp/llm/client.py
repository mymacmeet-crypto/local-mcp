"""Dispatches text-generation calls to whichever LLM backend is configured.

Set ``LLM_PROVIDER=ollama`` (default) to run ranking/summarization on a local
Ollama model, or ``LLM_PROVIDER=gemini`` to use the Google Gemini API instead.
Both backends implement the same ``generate_text`` signature, so callers (for
example ``local_mcp.tools.smart_search``) do not need to know which one is active.
"""

from __future__ import annotations

import os

from local_mcp.gemini import client as gemini
from local_mcp.ollama import client as ollama

PROVIDER = (os.environ.get("LLM_PROVIDER", "ollama").strip().lower()) or "ollama"


class LLMError(RuntimeError):
    """Raised when the configured LLM provider fails or is not usable."""


def is_configured() -> bool:
    if PROVIDER == "gemini":
        return gemini.has_api_key()
    return ollama.is_configured()


def not_configured_message() -> str:
    if PROVIDER == "gemini":
        return (
            "smart_search is set to use Gemini (LLM_PROVIDER=gemini) but no API key is "
            "configured. Set GEMINI_API_KEY in your .env, or set LLM_PROVIDER=ollama to "
            "use your local model instead."
        )
    return (
        "smart_search could not reach the local Ollama server. Make sure `ollama serve` "
        "is running and OLLAMA_MODEL is pulled (see .env.example)."
    )


async def generate_text(
    prompt: str,
    *,
    model: str | None = None,
    system: str | None = None,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
    response_mime_type: str | None = None,
) -> str:
    backend = gemini if PROVIDER == "gemini" else ollama
    try:
        return await backend.generate_text(
            prompt,
            model=model,
            system=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type=response_mime_type,
        )
    except (gemini.GeminiError, ollama.OllamaError) as err:
        raise LLMError(str(err)) from err
