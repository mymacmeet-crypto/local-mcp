"""Shared helper for fetching a page as Markdown with a browser fallback.

Fetch statically first, then fall back to browser rendering (crawl4ai) when the
static HTML yields thin content. Kept separate from ``tools/web.py`` so both the
``web_fetch`` tool and the composed ``smart_search`` tool reuse identical fetch
behavior.
"""

from __future__ import annotations

import os

from local_mcp.web import fetcher, html

MIN_MARKDOWN_CHARS = int(os.environ.get("LOCAL_MCP_MIN_MARKDOWN_CHARS", "200"))


def page_markdown(page: fetcher.FetchResult) -> str:
    """Return the page's Markdown, converting from HTML when none was supplied."""
    if page.markdown:
        return page.markdown
    return html.html_to_markdown(page.html, page.final_url)


async def fetch_auto(target: str) -> fetcher.FetchResult:
    """Fetch statically, falling back to browser rendering when static content is thin."""
    page = await fetcher.fetch_static(target)
    content = page_markdown(page)
    if len(content) < MIN_MARKDOWN_CHARS:
        try:
            rendered = await fetcher.fetch_browser(page.final_url)
        except Exception:
            return page
        if len(page_markdown(rendered)) > len(content):
            return rendered
    return page
