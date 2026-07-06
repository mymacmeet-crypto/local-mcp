"""MCP tool handlers for URL discovery and web fetching."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

from local_mcp.search import searxng
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
WEB_SUMMARY_CONCURRENCY = int(os.environ.get("LOCAL_MCP_WEB_SUMMARY_CONCURRENCY", "4"))

RENDER_MODES = {"auto", "static", "browser"}
WEB_FETCH_OUTPUT_FORMATS = {"markdown", "text", "html", "json"}
RenderMode = Literal["auto", "static", "browser"]
WebFetchOutputFormat = Literal["markdown", "text", "html", "json"]
SearchTimeRange = Literal["", "day", "month", "year"]


@dataclass(frozen=True)
class SummaryTarget:
    url: str
    title: str = ""
    snippet: str = ""
    source: str = "input"


@dataclass(frozen=True)
class PageSummary:
    target: SummaryTarget
    final_url: str
    status: int
    render_method: str
    title: str
    description: str
    summary: str
    content_characters: int
    warnings: list[str]


async def web_fetch(
    url: Annotated[str, Field(description="Page URL to fetch. Scheme-less input like `example.com` is allowed.")],
    render: Annotated[
        RenderMode,
        Field(description="Fetch mode: `auto` uses httpx first and browser fallback when content is thin; `static` uses only httpx; `browser` forces browser rendering."),
    ] = "auto",
    output_format: Annotated[
        WebFetchOutputFormat,
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


async def web_summarize(
    query: Annotated[
        str,
        Field(description="Optional web search query. When provided, SearXNG result URLs are fetched and summarized."),
    ] = "",
    urls: Annotated[
        str,
        Field(
            description=(
                "Optional URLs to summarize. Accepts comma/newline-separated URLs, raw web_search Markdown, "
                "or Markdown links. Use this for independent URL summarization."
            ),
        ),
    ] = "",
    limit: Annotated[
        int,
        Field(description="Maximum number of URLs to fetch and summarize.", ge=1, le=20),
    ] = 5,
    categories: Annotated[
        str,
        Field(description="SearXNG categories when query is provided, for example `general`, `news`, or `general,news`."),
    ] = "general",
    language: Annotated[
        str,
        Field(description="SearXNG language code when query is provided. Use `auto` for automatic language detection."),
    ] = "auto",
    pageno: Annotated[
        int,
        Field(description="SearXNG result page number when query is provided.", ge=1, le=20),
    ] = 1,
    safesearch: Annotated[
        int,
        Field(description="SearXNG safe-search level when query is provided: 0 off, 1 moderate, 2 strict.", ge=0, le=2),
    ] = 0,
    time_range: Annotated[
        SearchTimeRange,
        Field(description="Optional SearXNG time range when query is provided: `day`, `month`, or `year`."),
    ] = "",
    engines: Annotated[
        str,
        Field(description="Optional comma-separated SearXNG engines override when query is provided."),
    ] = "",
    searxng_url: Annotated[
        str,
        Field(description="Optional SearXNG base URL when query is provided."),
    ] = "",
    render: Annotated[
        RenderMode,
        Field(description="Fetch mode for each URL: `auto`, `static`, or `browser`."),
    ] = "auto",
    selector: Annotated[
        str,
        Field(description="Optional CSS selector to summarize a specific page region."),
    ] = "",
    summary_sentences: Annotated[
        int,
        Field(description="Maximum sentences per page summary.", ge=1, le=8),
    ] = 3,
    max_chars_per_page: Annotated[
        int,
        Field(description="Maximum extracted page characters to consider before summarizing.", ge=1000, le=100000),
    ] = 30000,
    include_failures: Annotated[
        bool,
        Field(description="Include URLs that failed to fetch in the response."),
    ] = True,
) -> str:
    """Search or fetch multiple URLs and return concise summaries instead of full page content."""
    cleaned_query = " ".join((query or "").split())
    render_mode = _validate_choice(render, RENDER_MODES, "render mode")
    selector = (selector or "").strip()
    targets = _targets_from_urls(urls)
    instance_url = ""

    if cleaned_query:
        try:
            instance_url, results, _answers, _suggestions = await searxng.search(
                cleaned_query,
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
        targets.extend(
            SummaryTarget(
                url=result.url,
                title=result.title,
                snippet=result.content,
                source="search",
            )
            for result in results
        )

    targets = _dedupe_targets(targets)[:limit]
    if not targets:
        raise tool_error("Provide either query or urls to summarize.")

    summaries, failures = await _summarize_targets(
        targets,
        query=cleaned_query,
        render_mode=render_mode,
        selector=selector,
        summary_sentences=summary_sentences,
        max_chars_per_page=max_chars_per_page,
    )
    if not summaries:
        details = "\n".join(f"- {url}: {message}" for url, message in failures)
        raise tool_error(f"Could not summarize any URLs.\n{details}".strip())

    return _format_web_summary_response(
        query=cleaned_query,
        input_url_count=len(_targets_from_urls(urls)),
        instance_url=instance_url,
        render_mode=render_mode,
        selector=selector,
        summaries=summaries,
        failures=failures if include_failures else [],
    )


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


async def _summarize_targets(
    targets: list[SummaryTarget],
    *,
    query: str,
    render_mode: str,
    selector: str,
    summary_sentences: int,
    max_chars_per_page: int,
) -> tuple[list[PageSummary], list[tuple[str, str]]]:
    semaphore = asyncio.Semaphore(max(1, WEB_SUMMARY_CONCURRENCY))

    async def summarize_one(target: SummaryTarget) -> PageSummary | tuple[str, str]:
        async with semaphore:
            try:
                return await _summarize_target(
                    target,
                    query=query,
                    render_mode=render_mode,
                    selector=selector,
                    summary_sentences=summary_sentences,
                    max_chars_per_page=max_chars_per_page,
                )
            except Exception as err:
                return (target.url, describe_fetch_error(err, target.url))

    results = await asyncio.gather(*(summarize_one(target) for target in targets))
    summaries: list[PageSummary] = []
    failures: list[tuple[str, str]] = []
    for result in results:
        if isinstance(result, PageSummary):
            summaries.append(result)
        else:
            failures.append(result)
    return summaries, failures


async def _summarize_target(
    target: SummaryTarget,
    *,
    query: str,
    render_mode: str,
    selector: str,
    summary_sentences: int,
    max_chars_per_page: int,
) -> PageSummary:
    warnings: list[str] = []
    page, render_method = await _fetch_for_mode(target.url, render_mode, "markdown", selector, warnings)
    metadata = html.extract_metadata(page.html, page.final_url)
    content = _content_for_page(page, "markdown", selector)
    if selector and not content:
        raise ValueError(f"No content found for selector {selector!r} at {page.final_url}.")

    summary_source = content[:max_chars_per_page]
    if not summary_source.strip():
        summary_source = "\n\n".join(value for value in (metadata.get("description", ""), target.snippet) if value)
    focus = " ".join(value for value in (query, target.title, target.snippet, metadata.get("title", "")) if value)
    summary = _summarize_text(summary_source, focus=focus, sentence_limit=summary_sentences)
    if not summary and target.snippet:
        summary = _limit_text(target.snippet, 600)
    if not summary:
        summary = "No readable summary could be extracted."

    return PageSummary(
        target=target,
        final_url=page.final_url,
        status=page.status,
        render_method=render_method,
        title=metadata.get("title") or target.title or page.final_url,
        description=metadata.get("description", ""),
        summary=summary,
        content_characters=len(content),
        warnings=warnings,
    )


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


def _targets_from_urls(raw_urls: str) -> list[SummaryTarget]:
    raw = raw_urls or ""
    targets: list[SummaryTarget] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = _clean_url_token(value)
        if not cleaned:
            return
        try:
            normalized = normalize_url(cleaned)
        except Exception:
            return
        if normalized in seen:
            return
        seen.add(normalized)
        targets.append(SummaryTarget(url=normalized))

    for match in re.finditer(r"\[[^\]]+\]\((https?://[^)\s]+)\)", raw):
        add(match.group(1))
    for match in re.finditer(r"https?://[^\s<>\]\"']+", raw):
        add(match.group(0))

    if targets:
        return targets

    for token in re.split(r"[\s,;]+", raw):
        cleaned = _clean_url_token(token)
        if "." in cleaned or cleaned.startswith(("localhost", "127.0.0.1")):
            add(cleaned)
    return targets


def _clean_url_token(value: str) -> str:
    return (value or "").strip().strip("`'\"<>[]{}").rstrip(").,;:")


def _dedupe_targets(targets: list[SummaryTarget]) -> list[SummaryTarget]:
    deduped: list[SummaryTarget] = []
    seen: set[str] = set()
    for target in targets:
        if target.url in seen:
            continue
        seen.add(target.url)
        deduped.append(target)
    return deduped


def _summarize_text(content: str, *, focus: str, sentence_limit: int) -> str:
    text = _markdown_to_plain_text(content)
    sentences = _sentence_candidates(text)
    if not sentences:
        return _limit_text(" ".join(text.split()), 600)

    focus_terms = set(_keywords(focus))
    word_counts = Counter(_keywords(text))
    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        words = _keywords(sentence)
        if not words:
            continue
        unique_words = set(words)
        score = 0.0
        score += sum(word_counts[word] for word in unique_words) / max(len(unique_words), 1)
        score += len(unique_words & focus_terms) * 4
        score += max(0.0, 3.0 - (index * 0.15))
        scored.append((score, index, sentence))

    if not scored:
        return _limit_text(" ".join(text.split()), 600)

    selected = sorted(sorted(scored, reverse=True)[:sentence_limit], key=lambda item: item[1])
    return _limit_text(" ".join(sentence for _score, _index, sentence in selected), 900)


def _markdown_to_plain_text(content: str) -> str:
    text = content or ""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[`*_>|]+", " ", text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _sentence_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for chunk in re.split(r"(?<=[.!?])\s+|\n+", text):
        cleaned = " ".join(chunk.split())
        if len(cleaned) < 40:
            continue
        if len(cleaned.split()) < 6:
            continue
        candidates.append(cleaned)
    if candidates:
        return candidates[:80]
    words = text.split()
    return [" ".join(words[index : index + 35]) for index in range(0, min(len(words), 210), 35)]


_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "before",
    "being",
    "between",
    "could",
    "from",
    "have",
    "into",
    "more",
    "other",
    "over",
    "than",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "through",
    "were",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
}


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", (text or "").lower())
    return [word for word in words if word not in _STOPWORDS]


def _limit_text(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


def _format_web_summary_response(
    *,
    query: str,
    input_url_count: int,
    instance_url: str,
    render_mode: str,
    selector: str,
    summaries: list[PageSummary],
    failures: list[tuple[str, str]],
) -> str:
    lines = ["Web summary:"]
    if query:
        lines.append(f"- Query: {query}")
    if instance_url:
        lines.append(f"- SearXNG instance: {instance_url}")
    if input_url_count:
        lines.append(f"- Input URLs parsed: {input_url_count}")
    lines.extend(
        [
            f"- Pages summarized: {len(summaries)}",
            f"- Fetch mode: {render_mode}",
        ]
    )
    if selector:
        lines.append(f"- Selector: {selector}")
    if failures:
        lines.append(f"- Failed URLs: {len(failures)}")

    overall = _summarize_text("\n".join(summary.summary for summary in summaries), focus=query, sentence_limit=4)
    if overall:
        lines.extend(["", "Overall summary:", overall])

    lines.append("")
    lines.append("Sources:")
    for index, summary in enumerate(summaries, start=1):
        lines.append(f"{index}. [{summary.title}]({markdown_link_target(summary.final_url)})")
        lines.append(f"   Summary: {summary.summary}")
        if summary.description:
            lines.append(f"   Description: {_limit_text(summary.description, 220)}")
        if summary.target.snippet:
            lines.append(f"   Search snippet: {_limit_text(summary.target.snippet, 220)}")
        lines.append(f"   URL: {summary.final_url}")
        lines.append(
            f"   Status: {summary.status} | Render: {summary.render_method} | Extracted characters: {summary.content_characters}"
        )
        if summary.warnings:
            lines.append(f"   Warnings: {'; '.join(summary.warnings)}")

    if failures:
        lines.extend(["", "Failures:"])
        lines.extend(f"- {url}: {message}" for url, message in failures)

    return "\n".join(lines)


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
