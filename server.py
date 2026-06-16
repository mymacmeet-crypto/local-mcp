"""claw-site MCP server.

Tools:
- extract URLs from a site using this flow:
robots.txt -> sitemap discovery -> sitemap parsing -> page fetch with httpx
-> link extraction, falling back to crawl4ai when static content has no links.
- extract text from images with Tesseract OCR.
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
import ocr  # noqa: E402
import sitemap  # noqa: E402
from errors import describe_fetch_error, normalize_url, tool_error  # noqa: E402

DEFAULT_LIMIT = int(os.environ.get("CLAW_SITE_URL_LIMIT", "500"))


@contextlib.asynccontextmanager
async def _lifespan(_server: "FastMCP"):
    try:
        yield
    finally:
        await fetcher.close_crawler()


mcp = FastMCP(
    "claw-site",
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


def _markdown_link_target(url: str) -> str:
    from urllib.parse import quote

    return quote(url, safe=":/?#[]@!$&'()*+,;=%")


with contextlib.suppress(Exception):
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_req: "Request") -> "JSONResponse":
        return JSONResponse({"status": "ok", "server": "claw-site"})


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
