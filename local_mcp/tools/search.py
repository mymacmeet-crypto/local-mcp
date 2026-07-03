"""MCP tool handler for SearXNG search."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from local_mcp.search import searxng
from local_mcp.shared.errors import tool_error
from local_mcp.shared.urls import markdown_link_target


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
        str,
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

    return format_search_response(
        query=query,
        instance_url=instance_url,
        results=results,
        answers=answers,
        suggestions=suggestions,
    )


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
