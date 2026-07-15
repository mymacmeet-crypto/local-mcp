"""MCP tool: `deep_research` — iterative, multi-source, verified web research.

Where `smart_search` runs a single pass (one search -> rank -> crawl -> one
summary), `deep_research` runs the same primitives in a decomposed, iterative
loop and returns a long-form, sectioned report:

    plan (sub-questions + outline)
      -> for each round, until done or budget spent:
           search fan-out (one search per open query, concurrently)
             -> rank the merged candidate pool
             -> crawl new pages (falling through failures)
             -> take per-source notes (an "evidence ledger", not raw dumps)
             -> reflect: what is still missing? -> new queries
      -> synthesize a cited report from the ledger following the outline
      -> verify: flag report claims the evidence does not support
      -> optionally write the report to a Markdown/PDF file

Keeping compact per-source notes (instead of concatenating whole pages into one
context, as `smart_search` does) is what lets this run on a small local Ollama
model and keeps citations honest. The LLM backend is pluggable exactly like
`smart_search` (local Ollama by default; `LLM_PROVIDER=gemini` for Gemini).
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import Field

from local_mcp.file_generation import write_generated_file
from local_mcp.llm import client as llm
from local_mcp.search import searxng
from local_mcp.shared import guidance
from local_mcp.shared.errors import tool_error
from local_mcp.shared.urls import normalize_url
from local_mcp.web import content

# `_clamp` and `_parse_indexes` are pure, tested utilities; reuse them so the
# JSON-index ranking parse behaves identically to `smart_search`.
from local_mcp.tools.smart_search import _clamp, _parse_indexes

# How many candidate results to pull per open query before ranking/dedup.
CANDIDATES_PER_QUERY = int(os.environ.get("LOCAL_MCP_DEEP_RESEARCH_CANDIDATES_PER_QUERY", "8"))
# Default new sources crawled per research round.
DEFAULT_BREADTH = int(os.environ.get("LOCAL_MCP_DEEP_RESEARCH_BREADTH", "4"))
# Default reflect -> re-search rounds (depth).
DEFAULT_MAX_ITERATIONS = int(os.environ.get("LOCAL_MCP_DEEP_RESEARCH_MAX_ITERATIONS", "2"))
# Default hard cap on total sources crawled across all rounds.
DEFAULT_MAX_SOURCES = int(os.environ.get("LOCAL_MCP_DEEP_RESEARCH_MAX_SOURCES", "12"))
# Per-source crawl content cap (characters) fed to the note-extraction step.
PER_SOURCE_MAX_CHARS = int(os.environ.get("LOCAL_MCP_DEEP_RESEARCH_SOURCE_CHARS", "12000"))
# Max new follow-up queries accepted from each reflection step.
MAX_FOLLOWUP_QUERIES = int(os.environ.get("LOCAL_MCP_DEEP_RESEARCH_FOLLOWUP_QUERIES", "4"))

SearchTimeRange = Literal["", "day", "month", "year"]

_NO_NOTES = "NO RELEVANT INFORMATION"


@dataclass
class Source:
    """One crawled page and the notes extracted from it (an evidence-ledger row)."""

    sid: int
    title: str
    url: str
    content: str
    notes: str = ""


@dataclass
class Plan:
    subquestions: list[str] = field(default_factory=list)
    outline: list[str] = field(default_factory=list)


async def deep_research(
    query: Annotated[str, Field(description="The research question or topic to investigate in depth.")],
    breadth: Annotated[
        int,
        Field(description="New sources to crawl per research round.", ge=1, le=10),
    ] = DEFAULT_BREADTH,
    max_iterations: Annotated[
        int,
        Field(description="How many reflect -> re-search rounds to run (research depth).", ge=1, le=4),
    ] = DEFAULT_MAX_ITERATIONS,
    max_sources: Annotated[
        int,
        Field(description="Hard cap on total pages crawled across all rounds.", ge=1, le=30),
    ] = DEFAULT_MAX_SOURCES,
    time_range: Annotated[
        SearchTimeRange,
        Field(description="Optional SearXNG time range: `day`, `month`, or `year`. Empty means any time."),
    ] = "",
    verify: Annotated[
        bool,
        Field(description="Run a fact-checking pass that flags report claims the sources do not support."),
    ] = True,
    output_file: Annotated[
        str,
        Field(
            description=(
                "Optional relative Markdown/PDF filename. When set, the report is also written to a file "
                "(under LOCAL_MCP_FILE_OUTPUT_DIR/LOCAL_MCP_DOWNLOAD_DIR) and its path is returned."
            )
        ),
    ] = "",
    model: Annotated[
        str,
        Field(description="Optional model override for the configured LLM provider. Empty uses the provider default."),
    ] = "",
) -> str:
    """Plan, iteratively search and read many sources, verify, and write a cited research report."""
    cleaned_query = query.strip()
    if not cleaned_query:
        raise tool_error("A non-empty query is required.")
    if not llm.is_configured():
        raise tool_error(llm.not_configured_message())

    model_override = model.strip() or None
    time = time_range.strip() or None
    max_sources = _clamp(max_sources, 1, 30)
    notes: list[str] = []  # narrator lines describing how the run unfolded

    # 1) PLAN — decompose the question into sub-questions and a report outline.
    plan = await _plan(cleaned_query, model_override)
    pending_queries = plan.subquestions or [cleaned_query]

    # 2) Iterative rounds: search -> rank -> crawl -> take notes -> reflect.
    sources: list[Source] = []
    seen_urls: set[str] = set()
    for iteration in range(max_iterations):
        if not pending_queries or len(sources) >= max_sources:
            break

        candidates = await _search_fanout(pending_queries, time, seen_urls)
        if not candidates:
            notes.append(f"Round {iteration + 1}: no new candidate sources for {pending_queries!r}.")
            break

        ranked = await _rank_results(cleaned_query, candidates, model_override)
        remaining = max_sources - len(sources)
        room = min(breadth, remaining)
        new_sources = await _crawl_new_sources(ranked, room, seen_urls, start_sid=len(sources) + 1)
        if not new_sources:
            notes.append(f"Round {iteration + 1}: found candidates but none could be crawled.")
            break

        # Take per-source notes tied to the question (the evidence ledger).
        for source in new_sources:
            source.notes = await _take_notes(cleaned_query, plan.subquestions, source, model_override)
        sources.extend(new_sources)
        notes.append(
            f"Round {iteration + 1}: crawled {len(new_sources)} new source(s) "
            f"({len(sources)}/{max_sources} total)."
        )

        # 3) REFLECT — decide whether to stop or open new queries for the next round.
        if iteration + 1 >= max_iterations or len(sources) >= max_sources:
            break
        pending_queries = await _reflect(cleaned_query, sources, model_override)
        if not pending_queries:
            notes.append(f"Round {iteration + 1}: reflection found no remaining gaps; stopping early.")
            break

    if not sources:
        raise tool_error(
            "Could not gather any evidence: no candidate URLs could be crawled. "
            "Try again, widen the query, or install the browser-render extra."
        )

    # 4) SYNTHESIZE the report from the evidence ledger, following the outline.
    try:
        report = await _synthesize(cleaned_query, plan.outline, sources, model_override)
    except llm.LLMError as err:
        raise tool_error(str(err))

    # 5) VERIFY — flag any claims the collected evidence does not support.
    verification = ""
    if verify:
        try:
            verification = await _verify(cleaned_query, sources, report, model_override)
        except llm.LLMError:
            verification = ""  # verification is best-effort; never fail the whole run on it.

    document = _format_report(report, verification, sources)

    if output_file.strip():
        try:
            written = write_generated_file(output_file.strip(), document, overwrite=True)
        except Exception as err:
            raise tool_error(f"Report generated but could not be written to a file: {err}")
        return f"Report written to: {written.path}\n\n{document}"

    return document


# --------------------------------------------------------------------------- #
# Pipeline stages                                                             #
# --------------------------------------------------------------------------- #


async def _plan(query: str, model: str | None) -> Plan:
    """Decompose the question into sub-questions and a report outline (best-effort)."""
    prompt = (
        f"You are planning a research report that answers this question:\n{query}\n\n"
        "Break it into focused sub-questions that, together, would fully cover the topic, and "
        "propose a section outline for the final report.\n"
        'Respond ONLY with JSON of the form '
        '{"subquestions": ["...", "..."], "outline": ["Section title", "..."]}. '
        "Provide 3 to 6 sub-questions and 3 to 6 outline sections."
    )
    try:
        raw = await llm.generate_text(
            prompt, model=model, temperature=0.0, response_mime_type="application/json"
        )
        data = json.loads(raw)
    except Exception:
        return Plan(subquestions=[query], outline=[])

    if not isinstance(data, dict):
        return Plan(subquestions=[query], outline=[])
    return Plan(
        subquestions=_string_list(data.get("subquestions"))[:6] or [query],
        outline=_string_list(data.get("outline"))[:6],
    )


async def _search_fanout(
    queries: list[str], time_range: str | None, seen_urls: set[str]
) -> list[searxng.SearchResult]:
    """Run one SearXNG search per open query concurrently, then merge and dedupe."""

    async def run(one_query: str) -> list[searxng.SearchResult]:
        try:
            _instance, results, _answers, _suggestions = await searxng.search(
                one_query, limit=CANDIDATES_PER_QUERY, time_range=time_range
            )
            return results
        except Exception:
            return []

    batches = await asyncio.gather(*(run(q) for q in queries))

    merged: list[searxng.SearchResult] = []
    batch_seen: set[str] = set()
    for batch in batches:
        for result in batch:
            key = result.url.rstrip("/")
            if key in seen_urls or key in batch_seen:
                continue
            batch_seen.add(key)
            merged.append(result)
    return merged


async def _rank_results(
    query: str, results: list[searxng.SearchResult], model: str | None
) -> list[searxng.SearchResult]:
    """Ask the LLM to rank the merged candidate pool best-first (falls back to search order)."""
    if len(results) <= 1:
        return results

    catalog = "\n".join(
        f"[{index}] {result.title}\n    url: {result.url}\n    snippet: {result.content or '(no snippet)'}"
        for index, result in enumerate(results)
    )
    prompt = (
        f"Research question:\n{query}\n\n"
        f"Here are {len(results)} candidate web search results:\n{catalog}\n\n"
        "Rank ALL of them from most to least likely to contain reliable, on-topic evidence. "
        "Prefer authoritative, specific, and recent sources, and favor a diverse set of domains. "
        'Respond ONLY with JSON of the form {"indexes": [<result numbers, best first>]}, '
        "including every result number exactly once."
    )
    try:
        raw = await llm.generate_text(
            prompt, model=model, temperature=0.0, response_mime_type="application/json"
        )
        order = _parse_indexes(raw, len(results))
    except Exception:
        return results

    if not order:
        return results
    seen = set(order)
    order.extend(index for index in range(len(results)) if index not in seen)
    return [results[index] for index in order]


async def _crawl_new_sources(
    ranked: list[searxng.SearchResult], room: int, seen_urls: set[str], *, start_sid: int
) -> list[Source]:
    """Crawl ranked results in order, adding up to ``room`` new pages that load."""
    added: list[Source] = []
    sid = start_sid
    for result in ranked:
        if len(added) >= room:
            break
        key = result.url.rstrip("/")
        if key in seen_urls:
            continue
        try:
            page = await content.fetch_auto(normalize_url(result.url))
            markdown = content.page_markdown(page).strip()
        except Exception:
            continue  # skip pages that time out, block, or render nothing
        seen_urls.add(key)
        if not markdown:
            continue
        added.append(
            Source(
                sid=sid,
                title=result.title or page.final_url,
                url=page.final_url,
                content=markdown[:PER_SOURCE_MAX_CHARS],
            )
        )
        sid += 1
    return added


async def _take_notes(
    query: str, subquestions: list[str], source: Source, model: str | None
) -> str:
    """Extract only the source's facts relevant to the question (keeps the ledger compact)."""
    system = (
        "You extract only the facts from a source that help answer a research question. Be faithful "
        "to the source and do not add outside knowledge. If the source has nothing relevant, reply "
        f"exactly with '{_NO_NOTES}'."
    )
    sub_bullets = "\n".join(f"- {sub}" for sub in subquestions) or "- (none)"
    prompt = (
        f"Research question:\n{query}\n\nSub-questions:\n{sub_bullets}\n\n"
        f"SOURCE [{source.sid}] {source.title}\nURL: {source.url}\n\nContent:\n{source.content}\n\n"
        "List the key facts, figures, dates, and claims from THIS source that are relevant to the "
        f"research question, as concise bullet points. Begin every bullet with the tag [{source.sid}]."
    )
    try:
        text = await llm.generate_text(prompt, model=model, system=system, temperature=0.0)
    except llm.LLMError:
        return ""
    return "" if text.strip().upper().startswith(_NO_NOTES) else text.strip()


async def _reflect(query: str, sources: list[Source], model: str | None) -> list[str]:
    """Given the evidence so far, return NEW follow-up queries (empty means stop)."""
    prompt = (
        f"Research question:\n{query}\n\nEvidence notes gathered so far:\n{_evidence_blob(sources)}\n\n"
        "Identify what is still missing, unverified, or one-sided in order to fully answer the "
        'question. Respond ONLY with JSON of the form '
        '{"done": <true|false>, "gaps": "<one short sentence>", "queries": ["<new web search query>"]}. '
        "Set done=true only if the notes already cover the question well. Otherwise provide 1 to "
        f"{MAX_FOLLOWUP_QUERIES} NEW, specific web search queries that target the gaps (not repeats)."
    )
    try:
        raw = await llm.generate_text(
            prompt, model=model, temperature=0.0, response_mime_type="application/json"
        )
        data = json.loads(raw)
    except Exception:
        return []

    if not isinstance(data, dict) or data.get("done") is True:
        return []
    return _string_list(data.get("queries"))[:MAX_FOLLOWUP_QUERIES]


async def _synthesize(
    query: str, outline: list[str], sources: list[Source], model: str | None
) -> str:
    """Write the long-form, inline-cited report from the evidence ledger."""
    system = (
        "You are a meticulous research analyst. Write a thorough, well-structured report that answers "
        "the question using ONLY the provided evidence notes. Cite sources inline as [1], [2], etc., "
        "matching the source ids. Follow the outline where sensible. Note where sources disagree or "
        "are thin. Do not invent facts or URLs."
    )
    outline_bullets = "\n".join(f"- {section}" for section in outline) or "- (choose a sensible structure)"
    prompt = (
        f"Question:\n{query}\n\nProposed outline:\n{outline_bullets}\n\n"
        f"Evidence notes (grouped by source id):\n{_evidence_blob(sources)}\n\n"
        "Write the full report now using Markdown headings and inline [n] citations. End with a short "
        "'## Limitations' section covering gaps and conflicting evidence."
    )
    return await llm.generate_text(prompt, model=model, system=system, temperature=0.3)


async def _verify(query: str, sources: list[Source], report: str, model: str | None) -> str:
    """Fact-check the report against the collected evidence; return a short audit note."""
    system = (
        "You are a fact-checking auditor. Given a report and the evidence notes it should be based on, "
        "identify statements in the report that the evidence does NOT support or that overstate it."
    )
    prompt = (
        f"Research question:\n{query}\n\nEvidence notes:\n{_evidence_blob(sources)}\n\nReport:\n{report}\n\n"
        "List each unsupported or overstated claim as a bullet, quoting the claim and explaining the "
        "issue. If every claim is supported by the evidence, reply exactly: "
        "'All claims are supported by the cited sources.'"
    )
    return await llm.generate_text(prompt, model=model, system=system, temperature=0.0)


# --------------------------------------------------------------------------- #
# Formatting helpers                                                          #
# --------------------------------------------------------------------------- #


def _evidence_blob(sources: list[Source]) -> str:
    """Render the evidence ledger for an LLM prompt, preferring notes over raw content."""
    blocks: list[str] = []
    for source in sources:
        body = source.notes or source.content[:1500]
        blocks.append(f"SOURCE [{source.sid}] {source.title}\nURL: {source.url}\n{body}")
    return "\n\n".join(blocks)


def _format_report(report: str, verification: str, sources: list[Source]) -> str:
    parts = [report.strip()]
    if verification.strip():
        parts.append(f"## Verification\n\n{verification.strip()}")
    source_lines = "\n".join(f"[{source.sid}] {source.url}" for source in sources)
    parts.append(f"## Sources\n\n{source_lines}")
    return "\n\n".join(parts)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        text = str(entry or "").strip()
        if text:
            items.append(text)
    return items


deep_research.__doc__ = guidance.DEEP_RESEARCH_DESCRIPTION
