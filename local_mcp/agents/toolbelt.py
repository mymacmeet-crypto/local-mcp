"""The curated set of local-mcp tools that team agents may call.

Each entry wraps an existing tool handler with a deliberately small schema so
weak local models can drive it via function calling. Handlers never raise:
failures come back as text so the agent can react (retry, pick another source)
instead of crashing the whole team run.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

RESULT_CHAR_LIMIT = int(os.environ.get("LOCAL_MCP_AGENT_TOOL_RESULT_CHARS", "8000"))

ToolHandler = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


async def _web_search(query: str = "", limit: int = 5) -> str:
    from local_mcp.tools import search

    return await search.web_search(query=str(query), limit=_clamp(limit, 1, 10))


async def _web_fetch(url: str = "", max_chars: int = 20_000) -> str:
    from local_mcp.tools import web

    return await web.web_fetch(url=str(url), max_chars=_clamp(max_chars, 1_000, 60_000))


async def _extract_urls(url: str = "", limit: int = 50) -> str:
    from local_mcp.tools import web

    return await web.extract_urls(url=str(url), limit=_clamp(limit, 1, 200))


async def _parse_document(document: str = "", pages: str = "") -> str:
    from local_mcp.tools import documents

    return await documents.parse_document(document=str(document), pages=str(pages), max_chars=60_000)


TOOLS: dict[str, AgentTool] = {
    "web_search": AgentTool(
        name="web_search",
        description="Search the web (SearXNG) and get candidate source URLs for a query.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Plain web search query."},
                "limit": {"type": "integer", "description": "Maximum URLs to return (1-10).", "default": 5},
            },
            "required": ["query"],
        },
        handler=_web_search,
    ),
    "web_fetch": AgentTool(
        name="web_fetch",
        description="Fetch one web page and return its content as Markdown.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Page URL to fetch."},
                "max_chars": {"type": "integer", "description": "Maximum characters to return.", "default": 20000},
            },
            "required": ["url"],
        },
        handler=_web_fetch,
    ),
    "extract_urls": AgentTool(
        name="extract_urls",
        description="List URLs found on a page or site (sitemaps and page links).",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Page or site URL to inspect."},
                "limit": {"type": "integer", "description": "Maximum URLs to return (1-200).", "default": 50},
            },
            "required": ["url"],
        },
        handler=_extract_urls,
    ),
    "parse_document": AgentTool(
        name="parse_document",
        description="Read a document (PDF, DOCX, ...) from a path or URL into Markdown.",
        parameters={
            "type": "object",
            "properties": {
                "document": {"type": "string", "description": "Document file path or URL."},
                "pages": {"type": "string", "description": "Optional page range like 1-3,5.", "default": ""},
            },
            "required": ["document"],
        },
        handler=_parse_document,
    ),
}


def tools_for(names: tuple[str, ...] | list[str]) -> list[AgentTool]:
    return [TOOLS[name] for name in names if name in TOOLS]


def ollama_schemas(tools: list[AgentTool]) -> list[dict[str, Any]]:
    """Tool schemas in the OpenAI-style format Ollama's /api/chat expects."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]


async def call_tool(name: str, arguments: Any, *, allowed: set[str]) -> str:
    """Run one agent-requested tool call, returning errors as text instead of raising."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except ValueError:
            return f"Error: tool arguments for {name!r} were not valid JSON."
    if not isinstance(arguments, dict):
        arguments = {}

    if name not in TOOLS:
        available = ", ".join(sorted(allowed)) or "none"
        return f"Error: unknown tool {name!r}. Your available tools: {available}."
    if name not in allowed:
        available = ", ".join(sorted(allowed)) or "none"
        return f"Error: tool {name!r} is not allowed for this agent. Your available tools: {available}."

    tool = TOOLS[name]
    known = set(tool.parameters.get("properties", {}))
    kwargs = {key: value for key, value in arguments.items() if key in known}
    try:
        result = await tool.handler(**kwargs)
    except Exception as err:  # noqa: BLE001 - agents must see failures as text
        return f"Error: {name} failed: {err}"
    return _truncate(str(result))


def _truncate(text: str) -> str:
    if RESULT_CHAR_LIMIT <= 0 or len(text) <= RESULT_CHAR_LIMIT:
        return text
    return text[:RESULT_CHAR_LIMIT].rstrip() + "\n... [tool result truncated]"


def _clamp(value: Any, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))
