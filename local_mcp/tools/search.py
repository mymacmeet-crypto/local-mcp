"""MCP tool handler for SearXNG search (discovery stage of web research)."""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import Field

from local_mcp.search import searxng
from local_mcp.shared import guidance
from local_mcp.shared.errors import tool_error


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


web_search.__doc__ = guidance.WEB_SEARCH_DESCRIPTION
