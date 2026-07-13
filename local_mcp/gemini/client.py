"""Thin async client for the Google Gemini (Generative Language) REST API.

Uses ``httpx`` directly rather than the heavy ``google-generativeai`` SDK to
avoid adding a dependency. Two configuration values are read from the
environment:

- ``GEMINI_API_KEY`` (or ``GOOGLE_API_KEY``): required to make any call.
- ``GEMINI_MODEL``: default model id, ``gemini-2.5-flash`` when unset.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest").strip() or "gemini-flash-latest"
API_BASE = os.environ.get(
    "GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta"
).rstrip("/")
TIMEOUT_MS = int(os.environ.get("GEMINI_TIMEOUT_MS", "120000"))
TIMEOUT_S = TIMEOUT_MS / 1000.0
# Retries for transient server errors (503/500/502/504). Quota/auth errors are not retried.
MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "2"))
RETRY_BACKOFF_S = float(os.environ.get("GEMINI_RETRY_BACKOFF_S", "2"))
_RETRYABLE_STATUS = {500, 502, 503, 504}


class GeminiError(RuntimeError):
    """Raised when a Gemini request fails or returns no usable text."""


def api_key() -> str:
    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        raise GeminiError(
            "GEMINI_API_KEY is not set. Add it to your .env file "
            "(see .env.example) to use Gemini-powered tools."
        )
    return key


def has_api_key() -> bool:
    return bool((os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip())


async def generate_text(
    prompt: str,
    *,
    model: str | None = None,
    system: str | None = None,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
    response_mime_type: str | None = None,
) -> str:
    """Call ``models/{model}:generateContent`` and return the concatenated text.

    Set ``response_mime_type='application/json'`` to ask Gemini to return a JSON
    document (useful for structured ranking output).
    """
    resolved_model = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    url = f"{API_BASE}/models/{resolved_model}:generateContent"

    generation_config: dict[str, Any] = {"temperature": temperature}
    if max_output_tokens:
        generation_config["maxOutputTokens"] = max_output_tokens
    if response_mime_type:
        generation_config["responseMimeType"] = response_mime_type

    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    headers = {"x-goog-api-key": api_key(), "Content-Type": "application/json"}

    last_error: GeminiError | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                response = await client.post(url, json=body, headers=headers)
        except httpx.HTTPError as err:
            last_error = GeminiError(f"Gemini request failed: {err}")
        else:
            if response.status_code < 400:
                try:
                    data = response.json()
                except ValueError as err:
                    raise GeminiError("Gemini returned a non-JSON response.") from err
                return _extract_text(data)
            # Non-retryable client errors (auth, quota, bad model) fail immediately.
            if response.status_code not in _RETRYABLE_STATUS:
                raise GeminiError(_describe_http_error(response, resolved_model))
            last_error = GeminiError(_describe_http_error(response, resolved_model))

        if attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_BACKOFF_S * (attempt + 1))

    raise last_error or GeminiError("Gemini request failed.")


def _describe_http_error(response: httpx.Response, model: str) -> str:
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = str((payload.get("error") or {}).get("message") or "").strip()
    except ValueError:
        detail = response.text.strip()[:300]

    status = response.status_code
    if status in (401, 403):
        return f"Gemini rejected the API key ({status}). {detail}".strip()
    if status == 404:
        return f"Gemini model '{model}' was not found (404). Check GEMINI_MODEL. {detail}".strip()
    if status == 429:
        return f"Gemini rate-limited the request (429). {detail}".strip()
    return f"Gemini returned HTTP {status}. {detail}".strip()


def _extract_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback") or {}
        blocked = feedback.get("blockReason")
        if blocked:
            raise GeminiError(f"Gemini blocked the prompt (reason: {blocked}).")
        raise GeminiError("Gemini returned no candidates.")

    parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    if not text:
        finish = (candidates[0] or {}).get("finishReason")
        if finish and finish != "STOP":
            raise GeminiError(f"Gemini returned no text (finishReason: {finish}).")
        raise GeminiError("Gemini returned an empty response.")
    return text
