"""Thin async client for a local Ollama server's chat API.

Two configuration values are read from the environment:

- ``OLLAMA_HOST``: base URL of the Ollama server (default ``http://127.0.0.1:11434``).
- ``OLLAMA_MODEL``: default model tag, e.g. ``qwen2.5:7b``.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b").strip() or "qwen2.5:7b"
HOST = (os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip() or "http://127.0.0.1:11434").rstrip("/")
TIMEOUT_MS = int(os.environ.get("OLLAMA_TIMEOUT_MS", "120000"))
TIMEOUT_S = TIMEOUT_MS / 1000.0
# Retries for transient server errors (503/500/502/504). Model-not-found is not retried.
MAX_RETRIES = int(os.environ.get("OLLAMA_MAX_RETRIES", "2"))
RETRY_BACKOFF_S = float(os.environ.get("OLLAMA_RETRY_BACKOFF_S", "2"))
_RETRYABLE_STATUS = {500, 502, 503, 504}


class OllamaError(RuntimeError):
    """Raised when an Ollama request fails or returns no usable text."""


def is_configured() -> bool:
    """Ollama needs no credentials, only a reachable server, so this is always true."""
    return True


async def generate_text(
    prompt: str,
    *,
    model: str | None = None,
    system: str | None = None,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
    response_mime_type: str | None = None,
) -> str:
    """Call ``/api/chat`` on the local Ollama server and return the reply text.

    Set ``response_mime_type='application/json'`` to ask Ollama to constrain the
    reply to valid JSON (useful for structured ranking output).
    """
    resolved_model = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    options: dict[str, Any] = {"temperature": temperature}
    if max_output_tokens:
        options["num_predict"] = max_output_tokens

    body: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "stream": False,
        "options": options,
    }
    if response_mime_type == "application/json":
        body["format"] = "json"

    data = await _request_chat(body, resolved_model)
    return _extract_text(data, resolved_model)


async def chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    """Call ``/api/chat`` with a full message history and optional tool schemas.

    Returns the raw assistant message dict. When the model wants to call a tool
    the dict carries a ``tool_calls`` list instead of (or alongside) ``content``.
    """
    resolved_model = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL

    options: dict[str, Any] = {"temperature": temperature}
    if max_output_tokens:
        options["num_predict"] = max_output_tokens

    body: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "stream": False,
        "options": options,
    }
    if tools:
        body["tools"] = tools

    data = await _request_chat(body, resolved_model)
    message = data.get("message")
    if not isinstance(message, dict):
        raise OllamaError(f"Ollama model '{resolved_model}' returned no message.")
    return message


async def _request_chat(body: dict[str, Any], model: str) -> dict[str, Any]:
    url = f"{HOST}/api/chat"
    last_error: OllamaError | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                response = await client.post(url, json=body)
        except httpx.HTTPError as err:
            last_error = OllamaError(
                f"Could not reach Ollama at {HOST}: {err}. Is `ollama serve` running?"
            )
        else:
            if response.status_code < 400:
                try:
                    return response.json()
                except ValueError as err:
                    raise OllamaError("Ollama returned a non-JSON response.") from err
            # Non-retryable client errors (bad model, bad request) fail immediately.
            if response.status_code not in _RETRYABLE_STATUS:
                raise OllamaError(_describe_http_error(response, model))
            last_error = OllamaError(_describe_http_error(response, model))

        if attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_BACKOFF_S * (attempt + 1))

    raise last_error or OllamaError("Ollama request failed.")


def _describe_http_error(response: httpx.Response, model: str) -> str:
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = str(payload.get("error") or "").strip()
    except ValueError:
        detail = response.text.strip()[:300]

    status = response.status_code
    if status == 404:
        return (
            f"Ollama model '{model}' was not found (404). "
            f"Pull it first with `ollama pull {model}`. {detail}"
        ).strip()
    return f"Ollama returned HTTP {status}. {detail}".strip()


def _extract_text(data: dict[str, Any], model: str) -> str:
    message = data.get("message") or {}
    text = str(message.get("content") or "").strip()
    if not text:
        raise OllamaError(f"Ollama model '{model}' returned an empty response.")
    return text
