"""SearXNG search client and formatting helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

DEFAULT_BASE_URL = os.environ.get("SEARXNG_BASE_URL", "http://127.0.0.1:8888")
DEFAULT_URLS = os.environ.get("SEARXNG_URLS") or os.environ.get("CLAW_SITE_SEARXNG_URLS")
TIMEOUT_MS = int(os.environ.get("SEARXNG_TIMEOUT_MS", os.environ.get("CLAW_SITE_TIMEOUT_MS", "15000")))
TIMEOUT_S = TIMEOUT_MS / 1000.0


@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    engines: list[str]
    published_date: str | None = None
    score: float | None = None


async def search(
    query: str,
    *,
    limit: int,
    categories: str = "general",
    language: str = "auto",
    pageno: int = 1,
    safesearch: int = 0,
    time_range: str | None = None,
    engines: str | None = None,
    base_url: str | None = None,
) -> tuple[str, list[SearchResult], list[str], list[str]]:
    """Run a SearXNG JSON search and return the instance, results, answers, suggestions."""
    cleaned_query = query.strip()
    if not cleaned_query:
        raise ValueError("Search query is required.")

    last_error: Exception | None = None
    for instance_url in _candidate_base_urls(base_url):
        try:
            data = await _request_search(
                instance_url,
                cleaned_query,
                categories=categories,
                language=language,
                pageno=pageno,
                safesearch=safesearch,
                time_range=time_range,
                engines=engines,
            )
            return (
                instance_url,
                _parse_results(data, limit=limit),
                _parse_text_list(data.get("answers")),
                _parse_text_list(data.get("suggestions")),
            )
        except Exception as err:
            last_error = err

    if last_error is None:
        raise RuntimeError("No SearXNG instance URL is configured.")
    raise last_error


async def _request_search(
    base_url: str,
    query: str,
    *,
    categories: str,
    language: str,
    pageno: int,
    safesearch: int,
    time_range: str | None,
    engines: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "q": query,
        "format": "json",
        "categories": categories,
        "language": language,
        "pageno": pageno,
        "safesearch": safesearch,
    }
    if time_range:
        params["time_range"] = time_range
    if engines:
        params["engines"] = engines

    url = urljoin(_normalize_base_url(base_url), "search")
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as client:
        response = await client.get(url, params=params)

    if response.status_code == 403:
        raise RuntimeError(
            f"{base_url} refused JSON search. Enable JSON output in SearXNG settings.yml "
            "with `search.formats: [html, json]`."
        )
    response.raise_for_status()

    try:
        data = response.json()
    except ValueError as err:
        raise RuntimeError(f"{base_url} did not return valid JSON.") from err
    if not isinstance(data, dict):
        raise RuntimeError(f"{base_url} returned an unexpected JSON payload.")
    return data


def _candidate_base_urls(explicit_base_url: str | None) -> list[str]:
    if explicit_base_url:
        return [_normalize_base_url(explicit_base_url)]

    raw_values = DEFAULT_URLS or DEFAULT_BASE_URL
    candidates = [_normalize_base_url(value) for value in raw_values.split(",") if value.strip()]
    return list(dict.fromkeys(candidates))


def _normalize_base_url(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("SearXNG base URL cannot be empty.")
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"http://{cleaned}"
    return cleaned.rstrip("/") + "/"


def _parse_results(data: dict[str, Any], *, limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen: set[str] = set()

    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = _clean_text(item.get("url"))
        title = _clean_text(item.get("title"))
        if not url or not title or url in seen:
            continue
        seen.add(url)
        results.append(
            SearchResult(
                title=title,
                url=url,
                content=_clean_text(item.get("content")),
                engines=_parse_text_list(item.get("engines") or item.get("engine")),
                published_date=_clean_text(item.get("publishedDate")) or None,
                score=_parse_score(item.get("score")),
            )
        )
        if len(results) >= limit:
            break

    return results


def _parse_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = _clean_text(value)
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            cleaned = _clean_text(item)
            if cleaned:
                values.append(cleaned)
        return values
    cleaned = _clean_text(value)
    return [cleaned] if cleaned else []


def _parse_score(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())
