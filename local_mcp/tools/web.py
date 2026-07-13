"""MCP tool handlers for URL discovery and web fetching."""

from __future__ import annotations

import json
import os
from typing import Annotated

from pydantic import Field

from local_mcp.shared import guidance
from local_mcp.shared.errors import describe_fetch_error, tool_error
from local_mcp.shared.urls import (
    markdown_link_target,
    normalize_url,
    same_hostname,
    same_path_prefix,
    url_route_path,
)
from local_mcp.web import content, fetcher, html, sitemap

DEFAULT_LIMIT = int(os.environ.get("LOCAL_MCP_URL_LIMIT", "500"))


async def web_fetch(
    url: Annotated[str, Field(description="Page URL to fetch. Scheme-less input like `example.com` is allowed.")],
    max_chars: Annotated[
        int,
        Field(description="Maximum `content` characters before truncation. Use 0 for no truncation.", ge=0, le=500000),
    ] = 120000,
) -> str:
    """Retrieve one web page as evidence: JSON with the page url and Markdown content."""
    target = normalize_url(url)

    try:
        page = await content.fetch_auto(target)
    except Exception as err:
        raise tool_error(describe_fetch_error(err, target))

    try:
        markdown = content.page_markdown(page)
    except Exception as err:
        raise tool_error(f"Could not scrape {page.final_url}: {err}")

    markdown, _ = _truncate(markdown, max_chars)
    if not markdown:
        raise tool_error(f"No extractable content found for {target}.")

    envelope: dict[str, object] = {
        "stage": "evidence",
        "url": target,
        "requires_analysis": True,
        "workflow": guidance.WORKFLOW,
        "agent_guidance": guidance.FETCH_RESULT_GUIDANCE,
        "next_action": guidance.FETCH_NEXT_ACTION,
        "content": markdown,
    }
    return json.dumps(envelope, ensure_ascii=False, indent=2)


async def extract_urls(
    url: Annotated[str, Field(description="Page or site URL. Scheme-less input like `example.com` is allowed.")],
    same_domain: Annotated[bool, Field(description="Only return URLs on the input URL hostname.")] = True,
    same_path: Annotated[
        bool,
        Field(description="Only return URLs under the input URL path prefix, such as /blogs and /blogs/..."),
    ] = True,
    limit: Annotated[int, Field(description="Maximum number of unique URLs to return.", ge=1, le=5000)] = DEFAULT_LIMIT,
) -> str:
    """Extract unique absolute URLs from robots/sitemaps and the given page."""
    target = normalize_url(url)
    route_scoped = same_path and url_route_path(target) != "/"
    urls: list[tuple[str, str]] = []
    seen: set[str] = set()
    render_methods: list[str] = []

    def mark_render_method(method: str) -> None:
        if method not in render_methods:
            render_methods.append(method)

    def should_include(value: str) -> bool:
        if same_domain and not same_hostname(value, target):
            return False
        if same_path and not same_path_prefix(value, target):
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

    static_links = html.extract_links(page.html, page.final_url, same_domain=same_domain)
    static_added = add_many(static_links, "httpx")

    if len(urls) < limit and (not static_links or static_added == 0 or route_scoped):
        try:
            mark_render_method("crawl4ai")
            rendered_page = await fetcher.fetch_browser(page.final_url)
            add_many(html.extract_links(rendered_page.html, rendered_page.final_url, same_domain=same_domain), "Crawl4AI")
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


def _truncate(content: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(content) <= max_chars:
        return content, False
    return content[:max_chars].rstrip(), True


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
    return f"- [{url}]({markdown_link_target(url)}) ({source})"


# Expose the full workflow guidance as the MCP tool description.
web_fetch.__doc__ = guidance.WEB_FETCH_DESCRIPTION
