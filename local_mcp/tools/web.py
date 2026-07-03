"""MCP tool handlers for URL, content, and web fetch extraction."""

from __future__ import annotations

import json
import os
from typing import Annotated

from pydantic import Field

from local_mcp.shared.errors import describe_fetch_error, tool_error
from local_mcp.shared.urls import (
    markdown_link_target,
    normalize_url,
    same_hostname,
    same_path_prefix,
    url_route_path,
)
from local_mcp.web import fetcher, html, sitemap

DEFAULT_LIMIT = int(os.environ.get("LOCAL_MCP_URL_LIMIT", "500"))
MIN_MARKDOWN_CHARS = int(os.environ.get("LOCAL_MCP_MIN_MARKDOWN_CHARS", "200"))
WEB_FETCH_LINK_LIMIT = int(os.environ.get("LOCAL_MCP_WEB_FETCH_LINK_LIMIT", "100"))
WEB_FETCH_IMAGE_LIMIT = int(os.environ.get("LOCAL_MCP_WEB_FETCH_IMAGE_LIMIT", "100"))

RENDER_MODES = {"auto", "static", "browser"}
WEB_FETCH_OUTPUT_FORMATS = {"markdown", "text", "html", "json"}


async def web_fetch(
    url: Annotated[str, Field(description="Page URL to fetch. Scheme-less input like `example.com` is allowed.")],
    render: Annotated[
        str,
        Field(description="Fetch mode: `auto` uses httpx first and browser fallback when content is thin; `static` uses only httpx; `browser` forces browser rendering."),
    ] = "auto",
    output_format: Annotated[
        str,
        Field(description="Returned content format: `markdown`, `text`, `html`, or `json`."),
    ] = "markdown",
    selector: Annotated[
        str,
        Field(description="Optional CSS selector for scraping a specific page region. Empty extracts the main/article/body content."),
    ] = "",
    include_links: Annotated[
        bool,
        Field(description="Include scraped links from the page or selected region."),
    ] = False,
    include_images: Annotated[
        bool,
        Field(description="Include scraped image URLs from the page or selected region."),
    ] = False,
    include_metadata: Annotated[
        bool,
        Field(description="Include fetch metadata before non-JSON content. JSON responses always include metadata."),
    ] = True,
    max_chars: Annotated[
        int,
        Field(description="Maximum content characters to return before truncation. Use 0 for no truncation.", ge=0, le=500000),
    ] = 120000,
) -> str:
    """Fetch, browser-render, or scrape a web page into Markdown, text, HTML, or JSON."""
    target = normalize_url(url)
    render_mode = _validate_choice(render, RENDER_MODES, "render mode")
    output = _validate_choice(output_format, WEB_FETCH_OUTPUT_FORMATS, "output format")
    selector = (selector or "").strip()
    warnings: list[str] = []

    try:
        page, render_method = await _fetch_for_mode(target, render_mode, output, selector, warnings)
    except Exception as err:
        raise tool_error(describe_fetch_error(err, target))

    try:
        metadata = html.extract_metadata(page.html, page.final_url)
        content = _content_for_page(page, output, selector)
        links = (
            html.extract_link_details(page.html, page.final_url, selector=selector, limit=WEB_FETCH_LINK_LIMIT)
            if include_links or output == "json"
            else []
        )
        images = (
            html.extract_images(page.html, page.final_url, selector=selector, limit=WEB_FETCH_IMAGE_LIMIT)
            if include_images or output == "json"
            else []
        )
    except Exception as err:
        raise tool_error(f"Could not scrape {page.final_url}: {err}")

    if selector and not content:
        raise tool_error(f"No content found for selector {selector!r} at {page.final_url}.")

    content, truncated = _truncate(content, max_chars)
    if truncated:
        warnings.append(f"Content truncated to {max_chars} characters.")

    if output == "json":
        payload = {
            "url": target,
            "final_url": page.final_url,
            "status": page.status,
            "render_method": render_method,
            "output_format": output,
            "selector": selector,
            "metadata": metadata,
            "warnings": warnings,
            "content": content,
            "links": links,
            "images": images,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    sections: list[str] = []
    if include_metadata:
        sections.append(
            _format_fetch_metadata(
                url=target,
                final_url=page.final_url,
                status=page.status,
                render_method=render_method,
                output_format=output,
                selector=selector,
                metadata=metadata,
                warnings=warnings,
            )
        )
    if content:
        sections.append(content)
    if include_links:
        sections.append(_format_links(links))
    if include_images:
        sections.append(_format_images(images))

    if not sections:
        raise tool_error(f"No extractable content found for {target}.")
    return "\n\n".join(section for section in sections if section).strip()


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


async def extract_content(
    url: Annotated[str, Field(description="Page URL to extract. Scheme-less input like `example.com` is allowed.")],
    include_title: Annotated[
        bool,
        Field(description="Prepend the page title as a top-level Markdown heading."),
    ] = True,
) -> str:
    """Extract a page's readable content and return it as Markdown."""
    target = normalize_url(url)

    try:
        page = await fetcher.fetch_static(target)
    except Exception as err:
        raise tool_error(describe_fetch_error(err, target))

    markdown = html.html_to_markdown(page.html, page.final_url)
    title = html.extract_title(page.html) if include_title else None

    if len(markdown) < MIN_MARKDOWN_CHARS:
        try:
            rendered = await fetcher.fetch_browser(page.final_url)
        except Exception:
            rendered = None
        if rendered is not None:
            rendered_md = rendered.markdown or html.html_to_markdown(rendered.html, rendered.final_url)
            if len(rendered_md) > len(markdown):
                markdown = rendered_md
                if include_title:
                    title = html.extract_title(rendered.html) or title

    if not markdown:
        raise tool_error(f"No extractable content found for {target}.")

    if include_title and title and not _starts_with_heading(markdown, title):
        return f"# {title}\n\n{markdown}"
    return markdown


def _starts_with_heading(markdown: str, title: str) -> bool:
    """True when the markdown already opens with `# <title>`."""
    first_line = next((line for line in markdown.splitlines() if line.strip()), "")
    stripped = first_line.lstrip("#").strip()
    return first_line.startswith("#") and stripped.casefold() == title.strip().casefold()


async def _fetch_for_mode(
    target: str,
    render_mode: str,
    output_format: str,
    selector: str,
    warnings: list[str],
) -> tuple[fetcher.FetchResult, str]:
    if render_mode == "browser":
        return await fetcher.fetch_browser(target), "Crawl4AI"

    page = await fetcher.fetch_static(target)
    if render_mode == "static":
        return page, "httpx"

    content = _content_for_page(page, output_format, selector)
    if output_format in {"markdown", "text", "json"} and len(content) < MIN_MARKDOWN_CHARS:
        try:
            rendered = await fetcher.fetch_browser(page.final_url)
        except Exception as err:
            warnings.append(f"Browser fallback unavailable: {err}")
        else:
            rendered_content = _content_for_page(rendered, output_format, selector)
            if len(rendered_content) > len(content):
                return rendered, "httpx + Crawl4AI"

    return page, "httpx"


def _content_for_page(page: fetcher.FetchResult, output_format: str, selector: str) -> str:
    if output_format == "markdown" and page.markdown and not selector:
        return page.markdown
    return _content_for_format(page.html, page.final_url, output_format, selector)


def _content_for_format(html_source: str, base_url: str, output_format: str, selector: str) -> str:
    if output_format == "markdown":
        return html.html_to_markdown(html_source, base_url, selector=selector)
    if output_format == "text":
        return html.html_to_text(html_source, selector=selector)
    if output_format == "html":
        return html.html_fragment(html_source, selector=selector)
    if output_format == "json":
        return html.html_to_markdown(html_source, base_url, selector=selector)
    raise tool_error(f"Unsupported output format: {output_format}.")


def _validate_choice(value: str, allowed: set[str], label: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))
        raise tool_error(f"Unsupported {label}: {value}. Choose one of: {choices}.")
    return normalized


def _truncate(content: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(content) <= max_chars:
        return content, False
    return content[:max_chars].rstrip(), True


def _format_fetch_metadata(
    *,
    url: str,
    final_url: str,
    status: int,
    render_method: str,
    output_format: str,
    selector: str,
    metadata: dict[str, str],
    warnings: list[str],
) -> str:
    lines = [
        "Fetch metadata:",
        f"- URL: {url}",
        f"- Final URL: {final_url}",
        f"- Status: {status}",
        f"- Render method: {render_method}",
        f"- Output format: {output_format}",
    ]
    if selector:
        lines.append(f"- Selector: {selector}")
    for key, value in metadata.items():
        label = key.replace("_", " ").title()
        lines.append(f"- {label}: {value}")
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines)


def _format_links(links: list[dict[str, str]]) -> str:
    if not links:
        return "Links: none"
    lines = ["Links:"]
    for link in links:
        text = link.get("text") or link["url"]
        lines.append(f"- [{text}]({markdown_link_target(link['url'])})")
    return "\n".join(lines)


def _format_images(images: list[dict[str, str]]) -> str:
    if not images:
        return "Images: none"
    lines = ["Images:"]
    for image in images:
        label = image.get("alt") or image.get("title") or image["url"]
        lines.append(f"- [{label}]({markdown_link_target(image['url'])})")
    return "\n".join(lines)


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
