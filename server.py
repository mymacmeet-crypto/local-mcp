"""Compatibility entry point for the packaged local-mcp server."""

from __future__ import annotations

from local_mcp.app import app, mcp
from local_mcp.cli import main
from local_mcp.tools.documents import parse_document
from local_mcp.tools.file_generation import generate_file
from local_mcp.tools.ocr import extract_image_text
from local_mcp.tools.search import web_search
from local_mcp.tools.web import extract_content, extract_urls

__all__ = [
    "app",
    "mcp",
    "main",
    "extract_urls",
    "extract_content",
    "web_search",
    "extract_image_text",
    "parse_document",
    "generate_file",
]


if __name__ == "__main__":
    main()


_UNUSED_LEGACY_SOURCE = r'''
"""local-mcp MCP server.

Tools:
- extract URLs from a site using this flow:
robots.txt -> sitemap discovery -> sitemap parsing -> page fetch with httpx
-> link extraction, falling back to crawl4ai when static content has no links.
- extract a page's readable content as Markdown (httpx -> HTML-to-Markdown,
  falling back to crawl4ai's native Markdown for JS-rendered pages).
- search the web through a self-hosted SearXNG instance.
- extract text from images with Tesseract OCR.
- parse PDFs and documents with local parser backends.
"""

from __future__ import annotations

import contextlib
import os
from typing import Annotated

from dotenv import load_dotenv

load_dotenv()

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from pydantic import Field  # noqa: E402

import extract  # noqa: E402
import fetcher  # noqa: E402
import document_parser  # noqa: E402
import ocr  # noqa: E402
import searxng  # noqa: E402
import sitemap  # noqa: E402
from errors import describe_fetch_error, normalize_url, tool_error  # noqa: E402

DEFAULT_LIMIT = int(os.environ.get("LOCAL_MCP_URL_LIMIT", "500"))


@contextlib.asynccontextmanager
async def _lifespan(_server: "FastMCP"):
    try:
        yield
    finally:
        await fetcher.close_crawler()


mcp = FastMCP(
    "local-mcp",
    lifespan=_lifespan,
    host=os.environ.get("MCP_HTTP_HOST", "127.0.0.1"),
    port=int(os.environ.get("MCP_HTTP_PORT", "3002")),
    # Behind a public host (Vercel) the inbound Host header is the deployment
    # domain, not localhost. FastMCP otherwise auto-enables DNS-rebinding
    # protection that only allows 127.0.0.1/localhost, so every request to the
    # streamable endpoint is rejected with "421 Invalid Host header". Disable it
    # here — DNS rebinding only threatens localhost-bound servers reachable from
    # a victim's browser, which a remote deployment is not.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
async def extract_urls(
    url: Annotated[str, Field(description="Page or site URL. Scheme-less input like `example.com` is allowed.")],
    same_domain: Annotated[bool, Field(description="Only return URLs on the input URL hostname.")] = True,
    same_path: Annotated[
        bool,
        Field(description="Only return URLs under the input URL path prefix, such as /blogs and /blogs/..."),
    ] = True,
    limit: Annotated[int, Field(description="Maximum number of unique URLs to return.", ge=1, le=5000)] = DEFAULT_LIMIT,
) -> str:
    """Extract unique absolute URLs from robots/sitemaps and the given page.

    The tool first checks robots.txt for Sitemap entries, parses discovered
    sitemaps, fetches the requested page with httpx, extracts links if present,
    and falls back to crawl4ai browser rendering when static HTML has no links.
    """
    target = normalize_url(url)
    route_scoped = same_path and _url_route_path(target) != "/"
    urls: list[tuple[str, str]] = []
    seen: set[str] = set()
    render_methods: list[str] = []

    def mark_render_method(method: str) -> None:
        if method not in render_methods:
            render_methods.append(method)

    def should_include(value: str) -> bool:
        if same_domain and not _same_hostname(value, target):
            return False
        if same_path and not _same_path_prefix(value, target):
            return False
        return True

    def add_url(value: str, source: str) -> bool:
        if len(urls) >= limit or not should_include(value) or value in seen:
            return False
        seen.add(value)
        urls.append((value, source))
        return True

    def add_many(values: list[str], source: str) -> int:
        return sum(1 for value in values if add_url(value, source))

    def add_sourced_many(values: list[tuple[str, str]]) -> int:
        return sum(1 for value, source in values if add_url(value, source))

    try:
        mark_render_method("httpx")
        add_sourced_many(await sitemap.collect_sitemap_urls(target, limit=limit, url_filter=should_include))
    except Exception:
        pass

    try:
        mark_render_method("httpx")
        page = await fetcher.fetch_static(target)
    except Exception as err:
        raise tool_error(describe_fetch_error(err, target))

    static_links = extract.extract_links(page.html, page.final_url, same_domain=same_domain)
    static_added = add_many(static_links, "httpx")

    if len(urls) < limit and (not static_links or static_added == 0 or route_scoped):
        try:
            mark_render_method("crawl4ai")
            rendered_page = await fetcher.fetch_browser(page.final_url)
            add_many(extract.extract_links(rendered_page.html, rendered_page.final_url, same_domain=same_domain), "Crawl4AI")
        except Exception as err:
            raise tool_error(describe_fetch_error(err, page.final_url))

    render_label = " + ".join(render_methods) or "none"
    stats_label = _format_url_stats(urls)
    if not urls:
        return f"Render method used: {render_label}\n{stats_label}\nNo URLs found for {target}."
    return (
        f"Render method used: {render_label}\n"
        f"{stats_label}\n"
        "URLs:\n"
        + "\n".join(_format_sourced_url(value, source) for value, source in urls)
    )


MIN_MARKDOWN_CHARS = int(os.environ.get("LOCAL_MCP_MIN_MARKDOWN_CHARS", "200"))


@mcp.tool()
async def extract_content(
    url: Annotated[str, Field(description="Page URL to extract. Scheme-less input like `example.com` is allowed.")],
    include_title: Annotated[
        bool,
        Field(description="Prepend the page title as a top-level Markdown heading."),
    ] = True,
) -> str:
    """Extract a page's readable content and return it as Markdown.

    Fetches the page with httpx and converts the HTML to Markdown. When the
    static HTML yields little content (e.g. a JS-rendered page), it falls back
    to crawl4ai browser rendering and uses its native Markdown output.
    """
    target = normalize_url(url)

    try:
        page = await fetcher.fetch_static(target)
    except Exception as err:
        raise tool_error(describe_fetch_error(err, target))

    markdown = extract.html_to_markdown(page.html, page.final_url)
    title = extract.extract_title(page.html) if include_title else None

    if len(markdown) < MIN_MARKDOWN_CHARS:
        try:
            rendered = await fetcher.fetch_browser(page.final_url)
        except Exception:
            rendered = None
        if rendered is not None:
            rendered_md = rendered.markdown or extract.html_to_markdown(rendered.html, rendered.final_url)
            if len(rendered_md) > len(markdown):
                markdown = rendered_md
                if include_title:
                    title = extract.extract_title(rendered.html) or title

    if not markdown:
        raise tool_error(f"No extractable content found for {target}.")

    if include_title and title and not _starts_with_heading(markdown, title):
        return f"# {title}\n\n{markdown}"
    return markdown


@mcp.tool()
async def web_search(
    query: Annotated[str, Field(description="Search query to send to SearXNG.")],
    limit: Annotated[int, Field(description="Maximum number of search results to return.", ge=1, le=20)] = 8,
    categories: Annotated[
        str,
        Field(description="SearXNG categories, for example `general`, `news`, `images`, or `general,news`."),
    ] = "general",
    language: Annotated[
        str,
        Field(description="SearXNG language code. Use `auto` for automatic language detection."),
    ] = "auto",
    pageno: Annotated[int, Field(description="SearXNG result page number.", ge=1, le=20)] = 1,
    safesearch: Annotated[
        int,
        Field(description="SearXNG safe-search level: 0 off, 1 moderate, 2 strict.", ge=0, le=2),
    ] = 0,
    time_range: Annotated[
        str,
        Field(description="Optional SearXNG time range: `day`, `month`, or `year`. Empty means any time."),
    ] = "",
    engines: Annotated[
        str,
        Field(description="Optional comma-separated SearXNG engines override. Empty uses the instance defaults."),
    ] = "",
    searxng_url: Annotated[
        str,
        Field(
            description=(
                "Optional SearXNG base URL for this request. Empty uses SEARXNG_URLS, "
                "LOCAL_MCP_SEARXNG_URLS, or SEARXNG_BASE_URL."
            )
        ),
    ] = "",
) -> str:
    """Search the web through SearXNG and return citation-ready Markdown results.

    Configure a local instance with SEARXNG_BASE_URL, or set SEARXNG_URLS /
    LOCAL_MCP_SEARXNG_URLS to a comma-separated failover list.
    """
    try:
        instance_url, results, answers, suggestions = await searxng.search(
            query,
            limit=limit,
            categories=categories,
            language=language,
            pageno=pageno,
            safesearch=safesearch,
            time_range=time_range.strip() or None,
            engines=engines.strip() or None,
            base_url=searxng_url.strip() or None,
        )
    except Exception as err:
        raise tool_error(f"SearXNG search failed: {err}")

    return _format_search_response(
        query=query,
        instance_url=instance_url,
        results=results,
        answers=answers,
        suggestions=suggestions,
    )


@mcp.tool()
async def extract_image_text(
    image: Annotated[
        str,
        Field(description="Image file path, image URL, data URL, or base64-encoded image content."),
    ],
    lang: Annotated[
        str,
        Field(description="Tesseract language code, for example 'eng' or 'eng+hin'."),
    ] = "eng",
) -> str:
    """Extract text from an image with Tesseract OCR.

    The response is only the recognized text, with no labels or metadata.
    """
    try:
        return await ocr.extract_image_text(image, lang=lang)
    except Exception as err:
        raise tool_error(str(err))


@mcp.tool()
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
    """Parse a PDF or document into Markdown, plain text, or JSON.

    The default `auto` backend prefers PyMuPDF4LLM when installed for fast
    digital PDFs, falls back to pypdf for lightweight text extraction, and can
    use optional Docling, Marker, MinerU, or pdfplumber backends when selected.
    """
    try:
        return await document_parser.parse_document(
            document,
            parser=parser,
            output_format=output_format,
            pages=pages,
            include_metadata=include_metadata,
            max_chars=max_chars,
        )
    except Exception as err:
        raise tool_error(str(err))


def _same_hostname(left_url: str, right_url: str) -> bool:
    from urllib.parse import urlparse

    return (urlparse(left_url).hostname or "") == (urlparse(right_url).hostname or "")


def _same_path_prefix(left_url: str, right_url: str) -> bool:
    if not _same_hostname(left_url, right_url):
        return False

    left_path = _url_route_path(left_url)
    right_path = _url_route_path(right_url)
    if right_path == "/":
        return True
    return left_path == right_path or left_path.startswith(f"{right_path}/")


def _url_route_path(url: str) -> str:
    from urllib.parse import urlparse

    return _normalize_route_path(urlparse(url).path)


def _normalize_route_path(path: str) -> str:
    return f"/{(path or '').strip('/')}"


def _starts_with_heading(markdown: str, title: str) -> bool:
    """True when the markdown already opens with `# <title>` (any heading level)."""
    first_line = next((line for line in markdown.splitlines() if line.strip()), "")
    stripped = first_line.lstrip("#").strip()
    return first_line.startswith("#") and stripped.casefold() == title.strip().casefold()


def _format_url_stats(urls: list[tuple[str, str]]) -> str:
    sources = ("robots.txt", "sitemap.xml", "httpx", "Crawl4AI")
    counts = {source: 0 for source in sources}
    for _url, source in urls:
        counts[source] = counts.get(source, 0) + 1

    lines = ["URL Stats:", f"- Total URLs: {len(urls)}"]
    lines.extend(f"- {source}: {counts[source]}" for source in sources)
    extra_sources = sorted(source for source in counts if source not in sources)
    lines.extend(f"- {source}: {counts[source]}" for source in extra_sources)
    return "\n".join(lines)


def _format_sourced_url(url: str, source: str) -> str:
    return f"- [{url}]({_markdown_link_target(url)}) ({source})"


def _format_search_response(
    *,
    query: str,
    instance_url: str,
    results: list[searxng.SearchResult],
    answers: list[str],
    suggestions: list[str],
) -> str:
    lines = [
        f'Search query: "{query.strip()}"',
        f"SearXNG instance: {instance_url}",
        f"Results returned: {len(results)}",
    ]

    if answers:
        lines.extend(["", "Answers:"])
        lines.extend(f"- {answer}" for answer in answers[:5])

    if not results:
        lines.extend(["", "No search results found."])
    else:
        lines.extend(["", "Results:"])
        for index, result in enumerate(results, start=1):
            lines.append(f"{index}. [{result.title}]({_markdown_link_target(result.url)})")
            if result.content:
                lines.append(f"   {result.content}")
            lines.append(f"   URL: {result.url}")
            metadata = _format_search_metadata(result)
            if metadata:
                lines.append(f"   {metadata}")

    if suggestions:
        lines.extend(["", "Suggestions:"])
        lines.extend(f"- {suggestion}" for suggestion in suggestions[:5])

    return "\n".join(lines)


def _format_search_metadata(result: searxng.SearchResult) -> str:
    metadata: list[str] = []
    if result.engines:
        metadata.append(f"Engines: {', '.join(result.engines)}")
    if result.published_date:
        metadata.append(f"Published: {result.published_date}")
    if result.score is not None:
        metadata.append(f"Score: {result.score:g}")
    return " | ".join(metadata)


def _markdown_link_target(url: str) -> str:
    from urllib.parse import quote

    return quote(url, safe=":/?#[]@!$&'()*+,;=%")


with contextlib.suppress(Exception):
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_req: "Request") -> "JSONResponse":
        return JSONResponse({"status": "ok", "server": "local-mcp"})


# Top-level ASGI application for serverless/ASGI hosts (e.g. Vercel, uvicorn).
# Vercel's Python runtime looks for a module-level `app`/`application`/`handler`.
app = mcp.streamable_http_app()


def main() -> None:
    import sys

    argv = sys.argv[1:]
    if "--http" in argv:
        mode = "http"
    elif "--stdio" in argv:
        mode = "stdio"
    else:
        mode = os.environ.get("MCP_TRANSPORT", "stdio").lower()

    if mode == "http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
'''
