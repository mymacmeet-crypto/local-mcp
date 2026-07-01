"""MCP tool handler for document parsing."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from local_mcp.documents import parse_document as parse_document_impl
from local_mcp.shared.errors import tool_error


async def parse_document(
    document: Annotated[
        str,
        Field(description="Document file path, file:// URI, HTTP(S) URL, data URL, or base64 document content."),
    ],
    parser: Annotated[
        str,
        Field(
            description=(
                "Parser backend: auto, pypdf, pymupdf4llm, pdfplumber, docling, marker, mineru, or text."
            ),
        ),
    ] = "auto",
    output_format: Annotated[
        str,
        Field(description="Output format: markdown, text, or json."),
    ] = "markdown",
    pages: Annotated[
        str,
        Field(description="Optional 1-based page range like '1-3,5'. Empty parses all pages."),
    ] = "",
    include_metadata: Annotated[
        bool,
        Field(description="Include parser/source metadata before markdown or text output."),
    ] = True,
    max_chars: Annotated[
        int,
        Field(description="Maximum returned content characters before truncation.", ge=1000, le=1_000_000),
    ] = 120_000,
) -> str:
    """Parse a PDF or document into Markdown, plain text, or JSON."""
    try:
        return await parse_document_impl(
            document,
            parser=parser,
            output_format=output_format,
            pages=pages,
            include_metadata=include_metadata,
            max_chars=max_chars,
        )
    except Exception as err:
        raise tool_error(str(err))
