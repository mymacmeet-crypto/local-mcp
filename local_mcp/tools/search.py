"""MCP tool handler for SearXNG search (discovery stage of web research)."""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import Field

from local_mcp.search import searxng
from local_mcp.shared import guidance
from local_mcp.shared.errors import tool_error
from local_mcp.shared.progress import Progress


async def web_search(
    query: Annotated[str, Field(description="Search query to send to SearXNG.")],
    limit: Annotated[int, Field(description="Maximum number of URLs to return.", ge=1, le=20)] = 8,
    ctx: Context | None = None,
) -> str:
    """Discover candidate source URLs for a question. Discovery only, not a final answer."""
    progress = Progress(ctx, total=2)
    await progress.report(f"Searching the web for {query.strip()!r}...")
    try:
        # answers/suggestions/instance are parsed by the client but omitted from this envelope.
        _instance_url, results, _answers, _suggestions = await searxng.search(query, limit=limit)
    except Exception as err:
        raise tool_error(f"SearXNG search failed: {err}")

    urls = [result.url for result in results]
    await progress.report(f"Found {len(urls)} candidate source(s).")
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


web_search.__doc__ = guidance.WEB_SEARCH_DESCRIPTION
