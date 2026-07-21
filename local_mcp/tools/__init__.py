"""MCP tool registration."""

from __future__ import annotations

import os
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

ToolHandler = Callable[..., object]

FULL_TOOL_PROFILES = {"", "full", "default"}
SIMPLE_TOOL_PROFILES = {"simple", "basic", "low", "low-model", "low_model", "qwen"}
BOTH_TOOL_PROFILES = {"both", "compat", "compatibility", "all"}


def register_tools(mcp: FastMCP) -> None:
    profile = os.environ.get("LOCAL_MCP_TOOL_PROFILE", "full")
    for tool in _tools_for_profile(profile):
        mcp.tool()(tool)


def _tools_for_profile(profile: str) -> tuple[ToolHandler, ...]:
    normalized = (profile or "full").strip().lower()
    if normalized in SIMPLE_TOOL_PROFILES:
        return _simple_tools()
    if normalized in BOTH_TOOL_PROFILES:
        return _dedupe_tools(_simple_tools() + _full_tools())
    if normalized not in FULL_TOOL_PROFILES:
        return _full_tools()
    return _full_tools()


def _dedupe_tools(tools: tuple[ToolHandler, ...]) -> tuple[ToolHandler, ...]:
    seen: set[str] = set()
    unique: list[ToolHandler] = []
    for tool in tools:
        name = getattr(tool, "__name__", repr(tool))
        if name not in seen:
            seen.add(name)
            unique.append(tool)
    return tuple(unique)


def _full_tools() -> tuple[ToolHandler, ...]:
    from local_mcp.tools import agents, deep_research, documents, file_generation, ocr, search, smart_search, web

    return (
        web.web_fetch,
        web.extract_urls,
        search.web_search,
        smart_search.smart_search,
        deep_research.deep_research,
        ocr.extract_image_text,
        documents.parse_document,
        file_generation.generate_file,
        agents.define_agent_team,
        agents.run_agent_team,
        agents.list_agent_teams,
        agents.delete_agent_team,
    )


def _simple_tools() -> tuple[ToolHandler, ...]:
    from local_mcp.tools import file_generation, simple

    return (
        simple.fetch_web_page,
        simple.list_page_urls,
        simple.read_document,
        simple.read_image_text,
        file_generation.generate_file,
        simple.run_agent_task,
    )
