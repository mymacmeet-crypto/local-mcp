"""MCP tool handler for SearXNG search."""

from __future__ import annotations

import os
from typing import Annotated, Literal

from pydantic import Field

from local_mcp.search import searxng
from local_mcp.shared.errors import tool_error
from local_mcp.shared.urls import markdown_link_target

SearchTimeRange = Literal["", "day", "month", "year"]
FOLLOW_UP_ENV = "LOCAL_MCP_WEB_SEARCH_FOLLOW_UP"
FOLLOW_UP_LIMIT_ENV = "LOCAL_MCP_WEB_SEARCH_FOLLOW_UP_LIMIT"
FOLLOW_UP_RENDER_ENV = "LOCAL_MCP_WEB_SEARCH_FOLLOW_UP_RENDER"
FOLLOW_UP_MAX_CHARS_ENV = "LOCAL_MCP_WEB_SEARCH_FOLLOW_UP_MAX_CHARS"
FOLLOW_UP_SUMMARY_SENTENCES_ENV = "LOCAL_MCP_WEB_SEARCH_SUMMARY_SENTENCES"


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
    """Search the web through SearXNG and return citation-ready Markdown results."""
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

    response = format_search_response(
        query=query,
        instance_url=instance_url,
        results=results,
        answers=answers,
        suggestions=suggestions,
        include_metadata=False,
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
    include_metadata: bool = True,
) -> str:
    lines: list[str] = []
    if include_metadata:
        lines = [
            f'Search query: "{query.strip()}"',
            f"SearXNG instance: {instance_url}",
            f"Results returned: {len(results)}",
        ]

    if answers:
        lines.extend(["", "Answers:"] if lines else ["Answers:"])
        lines.extend(f"- {answer}" for answer in answers[:5])

    if not results:
        lines.extend(["", "No search results found."] if lines else ["No search results found."])
    else:
        lines.extend([""] if lines else [])
        lines.append("Results:")
        for index, result in enumerate(results, start=1):
            lines.append(f"{index}. [{result.title}]({markdown_link_target(result.url)})")
            if result.content:
                lines.append(f"   {result.content}")
            if include_metadata:
                lines.append(f"   URL: {result.url}")
                metadata = _format_search_metadata(result)
                if metadata:
                    lines.append(f"   {metadata}")

    if include_metadata and suggestions:
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


async def _web_search_follow_up(results: list[searxng.SearchResult]) -> str:
    mode = _follow_up_mode()
    if mode == "none" or not results:
        return ""

    try:
        if mode == "summarize":
            return await _summarize_search_results(results)
        if mode == "fetch_first":
            return await _fetch_first_search_result(results[0])
    except Exception as err:
        return f"Follow-up {mode} failed: {err}"

    return ""


async def _summarize_search_results(results: list[searxng.SearchResult]) -> str:
    from local_mcp.tools import web as web_tools

    limit = min(len(results), _env_int(FOLLOW_UP_LIMIT_ENV, default=3, minimum=1, maximum=10))
    urls = "\n".join(f"- [{result.title}]({result.url})" for result in results[:limit])
    summary = await web_tools.web_summarize(
        urls=urls,
        limit=limit,
        render=os.environ.get(FOLLOW_UP_RENDER_ENV, "auto"),
        summary_sentences=_env_int(FOLLOW_UP_SUMMARY_SENTENCES_ENV, default=3, minimum=1, maximum=8),
        max_chars_per_page=_env_int(FOLLOW_UP_MAX_CHARS_ENV, default=20_000, minimum=1000, maximum=100_000),
    )
    return f"Follow-up web_summarize result:\n{summary}"


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
    if raw in {"", "0", "false", "no", "none", "off"}:
        return "none"
    if raw in {"summary", "summarize", "web_summarize", "web-summarize"}:
        return "summarize"
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
    if mode == "summarize":
        return (
            " The top results are already fetched and summarized above the raw "
            "results list in this response — treat that summary as the primary "
            "answer. Do not call web_summarize again on these URLs unless you "
            "need a different set of pages."
        )
    if mode == "fetch_first":
        return (
            " The top result's page is already fetched in full above the raw "
            "results list in this response — treat that content as the primary "
            "answer. Do not call web_fetch again on that URL unless you need a "
            "different page."
        )
    return ""


web_search.__doc__ = (
    "Search the web through SearXNG and return citation-ready Markdown results."
    + _describe_follow_up(_follow_up_mode())
)
