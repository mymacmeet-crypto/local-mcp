"""MCP tool handler for SearXNG search (discovery stage of web research)."""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import Field

from local_mcp.search import searxng
from local_mcp.shared import guidance
from local_mcp.shared.errors import tool_error
from local_mcp.shared.urls import markdown_link_target


async def web_search(
    query: Annotated[str, Field(description="Search query to send to SearXNG.")],
    limit: Annotated[int, Field(description="Maximum number of URLs to return.", ge=1, le=20)] = 8,
) -> str:
    """Discover candidate source URLs for a question. Discovery only, not a final answer."""
    try:
        # answers/suggestions/instance are parsed by the client but omitted from this envelope.
        _instance_url, results, _answers, _suggestions = await searxng.search(query, limit=limit)
    except Exception as err:
        raise tool_error(f"SearXNG search failed: {err}")

    urls = [result.url for result in results]
    payload: dict[str, Any] = {
        "stage": "discovery",
        "query": query.strip(),
        "requires_fetch": bool(urls),
        "workflow": guidance.WORKFLOW,
        "agent_guidance": guidance.SEARCH_RESULT_GUIDANCE,
        "next_action": guidance.SEARCH_NEXT_ACTION,
        "urls": urls,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


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


web_search.__doc__ = guidance.WEB_SEARCH_DESCRIPTION
