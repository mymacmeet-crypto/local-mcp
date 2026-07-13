"""Small, opinionated MCP tools for weaker tool-calling models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from local_mcp.tools import documents, file_generation, ocr, web

ReportFileType = Literal["md", "markdown", "pdf"]


async def fetch_web_page(
    url: Annotated[str, Field(description="Page URL to fetch. Scheme-less input like example.com is allowed.")],
    max_chars: Annotated[int, Field(description="Maximum characters to return.", ge=1000, le=120000)] = 50_000,
) -> str:
    """Fetch one web page as evidence (JSON with the page url and Markdown content).

    Read the returned content as source material, then write your own answer.
    Do not paste the raw content back to the user. Only provide url and optional
    max_chars.
    """
    return await web.web_fetch(url=url, max_chars=max_chars)


async def list_page_urls(
    url: Annotated[str, Field(description="Page or site URL to inspect for links.")],
    limit: Annotated[int, Field(description="Maximum URLs to return.", ge=1, le=500)] = 100,
) -> str:
    """List URLs found on a page or site using safe defaults."""
    return await web.extract_urls(url=url, same_domain=True, same_path=True, limit=limit)


async def read_document(
    document: Annotated[str, Field(description="Document file path, URL, data URL, or base64 document content.")],
    pages: Annotated[str, Field(description="Optional page range like 1-3,5. Empty reads all pages.")] = "",
) -> str:
    """Read a document into Markdown using automatic parser selection."""
    return await documents.parse_document(document=document, pages=pages, include_metadata=True, max_chars=120_000)


async def read_image_text(
    image: Annotated[str, Field(description="Image file path, image URL, data URL, or base64 image content.")],
) -> str:
    """Extract text from an image with default English OCR."""
    return await ocr.extract_image_text(image=image)


async def write_markdown_file(
    filename: Annotated[str, Field(description="Relative output Markdown filename or path.")],
    content: Annotated[str, Field(description="Markdown content to write.")],
    overwrite: Annotated[bool, Field(description="Replace the file if it already exists.")] = False,
) -> str:
    """Write Markdown content to the configured output folder."""
    return await file_generation.generate_file(
        filename=filename,
        content=content,
        file_type="md",
        overwrite=overwrite,
        write_mode="write",
    )


async def write_report_file(
    filename: Annotated[str, Field(description="Relative output filename or path for a complete report.")],
    content: Annotated[
        str,
        Field(
            description=(
                "Complete multi-section report content, not a short answer. Include heading, introduction, "
                "several detailed sections, examples or bullets, and conclusion."
            ),
        ),
    ],
    file_type: Annotated[
        ReportFileType,
        Field(description="Output file type: md/markdown or pdf. A .pdf filename also selects PDF output."),
    ] = "pdf",
    min_words: Annotated[
        int,
        Field(description="Minimum words required before writing. 900 is usually about 2-3 PDF pages.", ge=300, le=5000),
    ] = 900,
    overwrite: Annotated[bool, Field(description="Replace the file if it already exists.")] = False,
) -> str:
    """Write a complete multi-page report to PDF or Markdown; rejects short content."""
    return await file_generation.generate_file(
        filename=filename,
        content=content,
        file_type=file_type,
        overwrite=overwrite,
        write_mode="write",
        min_words=min_words,
    )


async def search_web_to_file(
    query: Annotated[str, Field(description="Plain web search query.")],
    filename: Annotated[str, Field(description="Relative Markdown or PDF output filename or path.")],
    limit: Annotated[int, Field(description="Number of search results to write.", ge=1, le=10)] = 5,
    overwrite: Annotated[bool, Field(description="Replace the file if it already exists.")] = False,
) -> str:
    """Search the web and write the results to a Markdown or PDF file."""
    return await file_generation.web_search_to_file(
        query=query,
        filename=filename,
        limit=limit,
        write_mode="write",
        overwrite=overwrite,
    )
