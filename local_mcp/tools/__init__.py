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
        return _simple_tools() + _full_tools()
    if normalized not in FULL_TOOL_PROFILES:
        return _full_tools()
    return _full_tools()


def _full_tools() -> tuple[ToolHandler, ...]:
    from local_mcp.tools import documents, file_generation, ocr, search, web

    return (
        web.web_fetch,
        web.extract_urls,
        search.web_search,
        ocr.extract_image_text,
        documents.parse_document,
        file_generation.generate_file,
        file_generation.web_search_to_file,
    )


def _simple_tools() -> tuple[ToolHandler, ...]:
    from local_mcp.tools import simple

    return (
        simple.fetch_web_page,
        simple.list_page_urls,
        simple.read_document,
        simple.read_image_text,
        simple.write_markdown_file,
        simple.write_report_file,
        simple.search_web_to_file,
    )
