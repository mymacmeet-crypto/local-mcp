"""MCP tool handler for SearXNG search."""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Annotated, Literal

from pydantic import Field

from local_mcp.search import searxng
from local_mcp.shared.errors import tool_error
from local_mcp.shared.urls import markdown_link_target

SearchTimeRange = Literal["", "day", "month", "year"]
FOLLOW_UP_ENV = "LOCAL_MCP_WEB_SEARCH_FOLLOW_UP"
FOLLOW_UP_RENDER_ENV = "LOCAL_MCP_WEB_SEARCH_FOLLOW_UP_RENDER"
FOLLOW_UP_MAX_CHARS_ENV = "LOCAL_MCP_WEB_SEARCH_FOLLOW_UP_MAX_CHARS"
OVERVIEW_SENTENCE_LIMIT = 4


async def web_search(
    query: Annotated[str, Field(description="Search query to send to SearXNG.")],
    limit: Annotated[int, Field(description="Maximum number of search results to return.", ge=1, le=20)] = 8,
    categories: Annotated[
        str,
        Field(description="SearXNG categories, for example `general`, `news`, `images`, or `general,news`."),
    ] = "general",
    language: Annotated[
        str,
        Field(description="SearXNG language code. Use `auto` for automatic language detection."),
    ] = "auto",
    pageno: Annotated[int, Field(description="SearXNG result page number.", ge=1, le=20)] = 1,
    safesearch: Annotated[
        int,
        Field(description="SearXNG safe-search level: 0 off, 1 moderate, 2 strict.", ge=0, le=2),
    ] = 0,
    time_range: Annotated[
        SearchTimeRange,
        Field(description="Optional SearXNG time range: `day`, `month`, or `year`. Empty means any time."),
    ] = "",
    engines: Annotated[
        str,
        Field(description="Optional comma-separated SearXNG engines override. Empty uses the instance defaults."),
    ] = "",
    searxng_url: Annotated[
        str,
        Field(
            description=(
                "Optional SearXNG base URL for this request. Empty uses SEARXNG_URLS, "
                "LOCAL_MCP_SEARXNG_URLS, or SEARXNG_BASE_URL."
            )
        ),
    ] = "",
) -> str:
    """Search the web through SearXNG and return an overall summary plus a source list."""
    try:
        instance_url, results, answers, suggestions = await searxng.search(
            query,
            limit=limit,
            categories=categories,
            language=language,
            pageno=pageno,
            safesearch=safesearch,
            time_range=time_range.strip() or None,
            engines=engines.strip() or None,
            base_url=searxng_url.strip() or None,
        )
    except Exception as err:
        raise tool_error(f"SearXNG search failed: {err}")

    response = _format_overview_response(
        query=query,
        results=results,
        answers=answers,
        suggestions=suggestions,
    )
    follow_up = await _web_search_follow_up(results)
    if follow_up:
        return f"{follow_up}\n\n{response}"
    return response


def format_search_response(
    *,
    query: str,
    instance_url: str,
    results: list[searxng.SearchResult],
    answers: list[str],
    suggestions: list[str],
) -> str:
    lines = [
        f'Search query: "{query.strip()}"',
        f"SearXNG instance: {instance_url}",
        f"Results returned: {len(results)}",
    ]

    if answers:
        lines.extend(["", "Answers:"])
        lines.extend(f"- {answer}" for answer in answers[:5])

    if not results:
        lines.extend(["", "No search results found."])
    else:
        lines.extend(["", "Results:"])
        for index, result in enumerate(results, start=1):
            lines.append(f"{index}. [{result.title}]({markdown_link_target(result.url)})")
            if result.content:
                lines.append(f"   {result.content}")
            lines.append(f"   URL: {result.url}")
            metadata = _format_search_metadata(result)
            if metadata:
                lines.append(f"   {metadata}")

    if suggestions:
        lines.extend(["", "Suggestions:"])
        lines.extend(f"- {suggestion}" for suggestion in suggestions[:5])

    return "\n".join(lines)


def _format_search_metadata(result: searxng.SearchResult) -> str:
    metadata: list[str] = []
    if result.engines:
        metadata.append(f"Engines: {', '.join(result.engines)}")
    if result.published_date:
        metadata.append(f"Published: {result.published_date}")
    if result.score is not None:
        metadata.append(f"Score: {result.score:g}")
    return " | ".join(metadata)


def _format_overview_response(
    *,
    query: str,
    results: list[searxng.SearchResult],
    answers: list[str],
    suggestions: list[str],
) -> str:
    if not results:
        return "No search results found."

    lines: list[str] = []
    if answers:
        lines.extend(["Answers:"])
        lines.extend(f"- {answer}" for answer in answers[:5])
        lines.append("")

    overview = _synthesize_overview(query, results)
    lines.extend(["Overall Summary:", "", overview or "No summary could be generated.", "", "Sources:", ""])
    for result in results:
        lines.append(result.title)
        lines.append(result.url)

    if suggestions:
        lines.extend(["", "Suggestions:"])
        lines.extend(f"- {suggestion}" for suggestion in suggestions[:5])

    return "\n".join(lines)


def _synthesize_overview(query: str, results: list[searxng.SearchResult]) -> str:
    candidates: list[str] = []
    for result in results:
        candidates.extend(_sentence_candidates(result.content))
    if not candidates:
        return ""

    focus_terms = set(_keywords(query))
    word_counts = Counter(word for candidate in candidates for word in _keywords(candidate))
    scored: list[tuple[float, int, str]] = []
    for index, candidate in enumerate(candidates):
        words = _keywords(candidate)
        if not words:
            continue
        unique_words = set(words)
        score = sum(word_counts[word] for word in unique_words) / max(len(unique_words), 1)
        score += len(unique_words & focus_terms) * 4
        scored.append((score, index, candidate))

    if not scored:
        return _limit_text(" ".join(candidates), 900)

    selected = sorted(sorted(scored, reverse=True)[:OVERVIEW_SENTENCE_LIMIT], key=lambda item: item[1])
    return _limit_text(" ".join(candidate for _score, _index, candidate in selected), 900)


def _sentence_candidates(text: str) -> list[str]:
    candidates = []
    for chunk in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        cleaned = " ".join(chunk.split())
        if len(cleaned) < 20:
            continue
        candidates.append(cleaned)
    return candidates


_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "before",
    "being",
    "between",
    "could",
    "from",
    "have",
    "into",
    "more",
    "other",
    "over",
    "than",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "through",
    "were",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
}


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", (text or "").lower())
    return [word for word in words if word not in _STOPWORDS]


def _limit_text(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


async def _web_search_follow_up(results: list[searxng.SearchResult]) -> str:
    mode = _follow_up_mode()
    if mode == "none" or not results:
        return ""

    try:
        if mode == "fetch_first":
            return await _fetch_first_search_result(results[0])
    except Exception as err:
        return f"Follow-up {mode} failed: {err}"

    return ""


async def _fetch_first_search_result(result: searxng.SearchResult) -> str:
    from local_mcp.tools import web as web_tools

    content = await web_tools.web_fetch(
        url=result.url,
        render=os.environ.get(FOLLOW_UP_RENDER_ENV, "auto"),
        max_chars=_env_int(FOLLOW_UP_MAX_CHARS_ENV, default=50_000, minimum=1000, maximum=500_000),
    )
    return f"Follow-up web_fetch result for top result ({result.url}):\n{content}"


def _follow_up_mode() -> str:
    raw = (os.environ.get(FOLLOW_UP_ENV) or "none").strip().lower()
    if raw in {"fetch", "fetch_first", "fetch-first", "web_fetch", "web-fetch"}:
        return "fetch_first"
    return "none"


def _env_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int((os.environ.get(name) or "").strip() or default)
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _describe_follow_up(mode: str) -> str:
    if mode == "fetch_first":
        return (
            " The top result's page is already fetched in full above the search "
            "summary in this response — treat that content as the primary "
            "answer. Do not call web_fetch again on that URL unless you need a "
            "different page."
        )
    return ""


web_search.__doc__ = (
    "Search the web through SearXNG and return an overall summary plus a source list."
    + _describe_follow_up(_follow_up_mode())
)
