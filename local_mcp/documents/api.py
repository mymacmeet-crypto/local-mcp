"""Public document parsing service."""

from __future__ import annotations

import asyncio

from local_mcp.documents.formatting import format_result, validate_choice
from local_mcp.documents.parsers import OUTPUT_FORMATS, PARSERS, parse_document_path
from local_mcp.documents.source import load_document_source


async def parse_document(
    document: str,
    *,
    parser: str = "auto",
    output_format: str = "markdown",
    pages: str = "",
    include_metadata: bool = True,
    max_chars: int = 120_000,
) -> str:
    """Parse a document source and return Markdown, text, or JSON."""
    parser_name = validate_choice(parser, PARSERS, "parser")
    format_name = validate_choice(output_format, OUTPUT_FORMATS, "output_format")
    source = await load_document_source(document)
    try:
        result = await asyncio.to_thread(
            parse_document_path,
            source.path,
            source.label,
            parser_name,
            format_name,
            pages,
        )
    finally:
        source.cleanup()

    return format_result(result, include_metadata=include_metadata, max_chars=max_chars)
