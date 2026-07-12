"""MCP tool handler for SearXNG search (discovery stage of web research)."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Annotated, Any, Literal

from pydantic import Field

from local_mcp.search import searxng
from local_mcp.shared import guidance, summarize
from local_mcp.shared.errors import tool_error
from local_mcp.shared.urls import markdown_link_target

SearchTimeRange = Literal["", "day", "month", "year"]

FOLLOW_UP_ENV = "LOCAL_MCP_WEB_SEARCH_FOLLOW_UP"
FOLLOW_UP_RENDER_ENV = "LOCAL_MCP_WEB_SEARCH_FOLLOW_UP_RENDER"
FOLLOW_UP_MAX_CHARS_ENV = "LOCAL_MCP_WEB_SEARCH_FOLLOW_UP_MAX_CHARS"
FOLLOW_UP_LIMIT_ENV = "LOCAL_MCP_WEB_SEARCH_FOLLOW_UP_LIMIT"
RECOMMENDED_URL_ENV = "LOCAL_MCP_WEB_SEARCH_RECOMMENDED_URLS"

# Weights blend the SearXNG engine score with query/snippet keyword overlap.
_ENGINE_SCORE_WEIGHT = 0.65
_KEYWORD_OVERLAP_WEIGHT = 0.35


async def web_search(
    query: Annotated[str, Field(description="Search query to send to SearXNG.")],
    limit: Annotated[int, Field(description="Maximum number of candidate results to return.", ge=1, le=20)] = 8,
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
    """Discover candidate web sources for a question. Discovery only, not a final answer."""
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

    payload = _build_search_payload(
        query=query,
        instance_url=instance_url,
        results=results,
        answers=answers,
        suggestions=suggestions,
    )

    prefetched = await _web_search_follow_up(results)
    if prefetched:
        payload["requires_fetch"] = False
        payload["agent_guidance"] = guidance.PREFETCHED_GUIDANCE
        payload["next_action"] = guidance.PREFETCHED_NEXT_ACTION
        payload["prefetched_sources"] = prefetched

    return json.dumps(payload, ensure_ascii=False, indent=2)


def _build_search_payload(
    *,
    query: str,
    instance_url: str,
    results: list[searxng.SearchResult],
    answers: list[str],
    suggestions: list[str],
) -> dict[str, Any]:
    scores = _relevance_scores(query, results)
    result_items: list[dict[str, Any]] = []
    for rank, (result, score) in enumerate(zip(results, scores), start=1):
        result_items.append(
            {
                "rank": rank,
                "title": result.title,
                "url": result.url,
                "snippet": result.content,
                "relevance_score": score,
                "engines": result.engines,
                "published_date": result.published_date,
            }
        )

    payload: dict[str, Any] = {
        "tool": "web_search",
        "stage": "discovery",
        "query": query.strip(),
        "searxng_instance": instance_url,
        "result_count": len(result_items),
        "requires_fetch": bool(result_items),
        "workflow": guidance.WORKFLOW,
        "agent_guidance": guidance.SEARCH_RESULT_GUIDANCE,
        "next_action": guidance.SEARCH_NEXT_ACTION,
        "recommended_urls": _recommended_urls(result_items),
        # SearXNG instant answers are hints only; still verify by fetching.
        "instant_answers": answers,
        "suggestions": suggestions,
        "results": result_items,
    }
    if not result_items:
        payload["note"] = "No search results found. Try a broader query, other categories, or different engines."
    return payload


def _relevance_scores(query: str, results: list[searxng.SearchResult]) -> list[float]:
    """Score each result in [0, 1] from engine rank/score and query keyword overlap."""
    if not results:
        return []

    query_terms = set(summarize.keywords(query))
    raw_scores = [result.score for result in results if result.score is not None]
    max_score = max(raw_scores) if raw_scores else 0.0
    total = len(results)

    scores: list[float] = []
    for index, result in enumerate(results):
        if result.score is not None and max_score > 0:
            engine_component = result.score / max_score
        else:
            engine_component = (total - index) / total
        text_terms = set(summarize.keywords(f"{result.title} {result.content}"))
        overlap = len(query_terms & text_terms) / len(query_terms) if query_terms else 0.0
        combined = _ENGINE_SCORE_WEIGHT * engine_component + _KEYWORD_OVERLAP_WEIGHT * overlap
        scores.append(round(max(0.0, min(1.0, combined)), 2))
    return scores


def _recommended_urls(result_items: list[dict[str, Any]]) -> list[str]:
    count = _env_int(RECOMMENDED_URL_ENV, default=3, minimum=1, maximum=10)
    ranked = sorted(result_items, key=lambda item: item["relevance_score"], reverse=True)
    urls: list[str] = []
    for item in ranked:
        if item["url"] not in urls:
            urls.append(item["url"])
        if len(urls) >= count:
            break
    return urls


def format_search_response(
    *,
    query: str,
    instance_url: str,
    results: list[searxng.SearchResult],
    answers: list[str],
    suggestions: list[str],
) -> str:
    """Citation-ready Markdown for file output (used by web_search_to_file)."""
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


async def _web_search_follow_up(results: list[searxng.SearchResult]) -> list[dict[str, Any]]:
    """Optionally prefetch top results server-side so weaker models get evidence.

    Returns a list of parsed ``web_fetch`` envelopes (empty when disabled).
    """
    mode = _follow_up_mode()
    if mode == "none" or not results:
        return []

    if mode == "fetch_first":
        targets = results[:1]
    else:  # summarize
        limit = _env_int(FOLLOW_UP_LIMIT_ENV, default=3, minimum=1, maximum=5)
        targets = results[:limit]

    envelopes = await asyncio.gather(
        *(_fetch_source_envelope(result) for result in targets),
        return_exceptions=True,
    )
    return [envelope for envelope in envelopes if isinstance(envelope, dict)]


async def _fetch_source_envelope(result: searxng.SearchResult) -> dict[str, Any]:
    from local_mcp.tools import web as web_tools

    raw = await web_tools.web_fetch(
        url=result.url,
        render=os.environ.get(FOLLOW_UP_RENDER_ENV, "auto"),
        max_chars=_env_int(FOLLOW_UP_MAX_CHARS_ENV, default=50_000, minimum=1000, maximum=500_000),
    )
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {"tool": "web_fetch", "url": result.url, "content": raw}


def _follow_up_mode() -> str:
    raw = (os.environ.get(FOLLOW_UP_ENV) or "none").strip().lower()
    if raw in {"fetch", "fetch_first", "fetch-first", "web_fetch", "web-fetch", "first"}:
        return "fetch_first"
    if raw in {"summarize", "summarise", "fetch_top", "fetch-top", "top"}:
        return "summarize"
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
            " Server-side follow-up is ON (fetch_first): the top result is "
            "already fetched into `prefetched_sources` and `requires_fetch` is "
            "false, so analyze that evidence and answer directly."
        )
    if mode == "summarize":
        return (
            " Server-side follow-up is ON (summarize): the top results are "
            "already fetched into `prefetched_sources` and `requires_fetch` is "
            "false, so analyze that evidence and answer directly."
        )
    return ""


web_search.__doc__ = guidance.WEB_SEARCH_DESCRIPTION + _describe_follow_up(_follow_up_mode())
