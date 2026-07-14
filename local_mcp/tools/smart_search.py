"""MCP tool: `smart_search` — a one-shot, LLM-powered web answer.

Pipeline: SearXNG search -> the configured LLM ranks and selects the most
relevant URLs -> crawl the selected pages -> the LLM writes a cited summary ->
return the summary plus the source list. Unlike the discovery-only
`web_search`, this tool returns a final synthesized answer. The LLM backend is
local Ollama by default; set `LLM_PROVIDER=gemini` to use Google Gemini instead.
"""

from __future__ import annotations

import json
import os
import re
from typing import Annotated, Literal

from pydantic import Field

from local_mcp.llm import client as llm
from local_mcp.search import searxng
from local_mcp.shared import guidance
from local_mcp.shared.errors import tool_error
from local_mcp.shared.urls import normalize_url
from local_mcp.web import content

# How many candidate results to pull from search before the LLM ranks them.
CANDIDATE_MULTIPLIER = int(os.environ.get("LOCAL_MCP_SMART_SEARCH_CANDIDATES", "4"))
MIN_CANDIDATES = 6
MAX_CANDIDATES = 20
# Per-source crawl content cap (characters) fed to the LLM for summarization.
PER_SOURCE_MAX_CHARS = int(os.environ.get("LOCAL_MCP_SMART_SEARCH_SOURCE_CHARS", "16000"))

SearchTimeRange = Literal["", "day", "month", "year"]


async def smart_search(
    query: Annotated[str, Field(description="The question or topic to research and answer.")],
    max_sources: Annotated[
        int,
        Field(description="Maximum number of pages to crawl and summarize.", ge=1, le=10),
    ] = 3,
    time_range: Annotated[
        SearchTimeRange,
        Field(description="Optional SearXNG time range: `day`, `month`, or `year`. Empty means any time."),
    ] = "",
    model: Annotated[
        str,
        Field(
            description=(
                "Optional model override for the configured LLM provider. Empty uses "
                "OLLAMA_MODEL (default qwen2.5:7b) or GEMINI_MODEL if LLM_PROVIDER=gemini."
            )
        ),
    ] = "",
) -> str:
    """Search the web, pick the best sources with the configured LLM, crawl them, and return a cited summary."""
    cleaned_query = query.strip()
    if not cleaned_query:
        raise tool_error("A non-empty query is required.")
    if not llm.is_configured():
        raise tool_error(llm.not_configured_message())

    model_override = model.strip() or None

    # 1) Discover candidate sources.
    candidate_limit = _clamp(max_sources * CANDIDATE_MULTIPLIER, MIN_CANDIDATES, MAX_CANDIDATES)
    try:
        _instance_url, results, _answers, _suggestions = await searxng.search(
            cleaned_query,
            limit=candidate_limit,
            time_range=time_range.strip() or None,
        )
    except Exception as err:
        raise tool_error(f"SearXNG search failed: {err}")

    if not results:
        raise tool_error(f"No web results found for {cleaned_query!r}.")

    # 2) Let the LLM rank ALL candidates best-first (fall back to search order).
    ranked = await _rank_urls(cleaned_query, results, model_override)

    # 3) Crawl down the ranked list until enough pages load successfully.
    sources = await _crawl_sources(ranked, max_sources)
    if not sources:
        raise tool_error(
            "Found candidate URLs but could not crawl any of them. "
            "Try again or widen the query."
        )

    # 4) Summarize the crawled evidence with the LLM.
    try:
        summary = await _summarize(cleaned_query, sources, model_override)
    except llm.LLMError as err:
        raise tool_error(str(err))

    return _format_answer(summary, sources)


async def _rank_urls(
    query: str,
    results: list[searxng.SearchResult],
    model: str | None,
) -> list[searxng.SearchResult]:
    """Ask the LLM to rank ALL results best-first; fall back to search order on any failure.

    Returns every result reordered by relevance so the crawl step can fall through
    to lower-ranked sources when a higher-ranked page fails to load.
    """
    if len(results) <= 1:
        return results

    catalog = "\n".join(
        f"[{index}] {result.title}\n    url: {result.url}\n    snippet: {result.content or '(no snippet)'}"
        for index, result in enumerate(results)
    )
    prompt = (
        f"User question:\n{query}\n\n"
        f"Here are {len(results)} candidate web search results:\n{catalog}\n\n"
        "Rank ALL of them from most to least likely to contain a reliable, on-topic answer. "
        "Prefer authoritative, specific, and recent sources. "
        'Respond ONLY with JSON of the form {"indexes": [<result numbers, best first>]}, '
        "including every result number exactly once."
    )

    try:
        raw = await llm.generate_text(
            prompt,
            model=model,
            temperature=0.0,
            response_mime_type="application/json",
        )
        order = _parse_indexes(raw, len(results))
    except Exception:
        return results

    if not order:
        return results
    # Append any indexes the LLM omitted, preserving original search order.
    seen = set(order)
    order.extend(index for index in range(len(results)) if index not in seen)
    return [results[index] for index in order]


async def _crawl_sources(
    ranked: list[searxng.SearchResult], max_sources: int
) -> list[dict[str, str]]:
    """Crawl ranked results in order, keeping the first ``max_sources`` that load."""
    sources: list[dict[str, str]] = []
    for result in ranked:
        if len(sources) >= max_sources:
            break
        try:
            target = normalize_url(result.url)
            page = await content.fetch_auto(target)
            markdown = content.page_markdown(page).strip()
        except Exception:
            # Skip pages that fail to load (timeout, block, etc.) and try the next.
            continue
        if not markdown:
            continue
        sources.append(
            {
                "title": result.title or page.final_url,
                "url": page.final_url,
                "content": markdown[:PER_SOURCE_MAX_CHARS],
            }
        )
    return sources


async def _summarize(query: str, sources: list[dict[str, str]], model: str | None) -> str:
    blocks = "\n\n".join(
        f"SOURCE [{index}] {source['title']}\nURL: {source['url']}\n{source['content']}"
        for index, source in enumerate(sources, start=1)
    )
    system = (
        "You are a research assistant. Answer the user's question using ONLY the provided sources. "
        "Write a clear, well-structured summary. Cite sources inline as [1], [2], etc. matching the "
        "SOURCE numbers. If the sources disagree or do not answer the question, say so. Do not invent "
        "facts or URLs."
    )
    prompt = f"Question:\n{query}\n\nSources:\n{blocks}\n\nWrite the cited answer now."
    return await llm.generate_text(prompt, model=model, system=system, temperature=0.3)


def _format_answer(summary: str, sources: list[dict[str, str]]) -> str:
    lines = [summary.strip(), "", "Sources:"]
    lines.extend(f"[{index}] {source['url']}" for index, source in enumerate(sources, start=1))
    return "\n".join(lines)


def _parse_indexes(raw: str, count: int) -> list[int]:
    text = raw.strip()
    try:
        data = json.loads(text)
    except ValueError:
        # Fall back to pulling the first integers out of the text.
        numbers = [int(n) for n in re.findall(r"\d+", text)]
        return _dedupe_valid(numbers, count)

    values = data.get("indexes") if isinstance(data, dict) else data
    if not isinstance(values, list):
        return []
    indexes: list[int] = []
    for value in values:
        try:
            indexes.append(int(value))
        except (TypeError, ValueError):
            continue
    return _dedupe_valid(indexes, count)


def _dedupe_valid(indexes: list[int], count: int) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for index in indexes:
        if 0 <= index < count and index not in seen:
            seen.add(index)
            result.append(index)
    return result


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


smart_search.__doc__ = guidance.SMART_SEARCH_DESCRIPTION
