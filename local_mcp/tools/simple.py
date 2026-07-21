"""Small, opinionated MCP tools for weaker tool-calling models."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from local_mcp.tools import documents, ocr, web


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


async def run_agent_task(
    task: Annotated[str, Field(description="The task or question for the agent team to work on.")],
    team: Annotated[
        str,
        Field(description="Team to run: `research` (researcher + writer) or `research-review` (adds a reviewer)."),
    ] = "research",
) -> str:
    """Run a small multi-agent team (a web researcher, then a writer) on a task and return its answer."""
    from local_mcp.tools import agents

    return await agents.run_agent_team(team=team, task=task)
