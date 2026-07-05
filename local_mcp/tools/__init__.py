"""MCP tool registration."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    from local_mcp.tools import documents, file_generation, ocr, search, web

    for tool in (
        web.web_fetch,
        web.web_summarize,
        web.extract_urls,
        search.web_search,
        ocr.extract_image_text,
        documents.parse_document,
        file_generation.generate_file,
        file_generation.web_search_to_file,
    ):
        mcp.tool()(tool)
