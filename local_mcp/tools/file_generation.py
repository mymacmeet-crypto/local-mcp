"""MCP tool handler for file generation."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field

from local_mcp.file_generation import GeneratedFile, append_generated_file, write_generated_file
from local_mcp.search import searxng
from local_mcp.shared.errors import tool_error
from local_mcp.tools.search import format_search_response

FileType = Literal["md", "markdown", "pdf"]
SearchTimeRange = Literal["", "day", "month", "year"]
WriteMode = Literal["write", "append"]


async def generate_file(
    filename: Annotated[
        str,
        Field(
            description=(
                "Output Markdown or PDF filename or relative path. The extension is appended when omitted."
            ),
        ),
    ],
    content: Annotated[
        str,
        Field(description="Markdown-like content to write into the generated Markdown or PDF file."),
    ],
    file_type: Annotated[
        FileType,
        Field(description="Output file type: md/markdown or pdf. A .pdf filename also selects PDF output."),
    ] = "md",
    overwrite: Annotated[
        bool,
        Field(description="Replace an existing file at the target path."),
    ] = False,
    write_mode: Annotated[
        WriteMode,
        Field(description="Write mode: `write` creates/replaces content, `append` adds this content as a chunk."),
    ] = "write",
    ensure_trailing_newline: Annotated[
        bool,
        Field(description="Append a trailing newline to non-empty Markdown content. Ignored for PDF output."),
    ] = True,
    min_words: Annotated[
        int,
        Field(
            description=(
                "Minimum word count required before writing. Use 700-1200 for a 2-3 page report. "
                "Use 0 to allow short notes."
            ),
            ge=0,
            le=20000,
        ),
    ] = 0,
) -> str:
    """Generate a local Markdown or PDF file from supplied content."""
    try:
        _validate_min_words(content, min_words)
        result = _write_content_to_file(
            filename,
            content,
            file_type=file_type,
            overwrite=overwrite,
            write_mode=write_mode,
            ensure_trailing_newline=ensure_trailing_newline,
        )
    except Exception as err:
        raise tool_error(str(err))

    return _format_generated_file_result(result)


async def web_search_to_file(
    query: Annotated[str, Field(description="Search query to send to SearXNG.")],
    filename: Annotated[
        str,
        Field(
            description=(
                "Output Markdown or PDF filename or relative path. The matching extension is appended when omitted."
            ),
        ),
    ],
    limit: Annotated[int, Field(description="Maximum number of search results to write.", ge=1, le=20)] = 8,
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
        SearchTimeRange,
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
    write_mode: Annotated[
        WriteMode,
        Field(description="File write mode: `append` adds the search section, `write` creates/replaces content."),
    ] = "append",
    overwrite: Annotated[
        bool,
        Field(description="Replace an existing file when write_mode is `write`."),
    ] = False,
    ensure_trailing_newline: Annotated[
        bool,
        Field(description="Append a trailing newline to the generated Markdown section. Ignored for PDF output."),
    ] = True,
    file_type: Annotated[
        FileType,
        Field(description="Output file type: md/markdown or pdf. A .pdf filename also selects PDF output."),
    ] = "md",
) -> str:
    """Search the web and write citation-ready results directly to a local Markdown or PDF file."""
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

    markdown = _format_search_file_section(
        query=query,
        instance_url=instance_url,
        results=results,
        answers=answers,
        suggestions=suggestions,
    )

    try:
        result = _write_content_to_file(
            filename,
            markdown,
            file_type=file_type,
            overwrite=overwrite,
            write_mode=write_mode,
            ensure_trailing_newline=ensure_trailing_newline,
        )
    except Exception as err:
        raise tool_error(str(err))

    return "\n".join(
        [
            "Web search results written to file.",
            f"- Query: {query.strip()}",
            f"- SearXNG instance: {instance_url}",
            f"- Results returned: {len(results)}",
            f"- Path: {result.path}",
            f"- File type: {result.file_type}",
            f"- Write mode: {result.operation}",
            f"- Characters written: {result.characters_written}",
            f"- Bytes written: {result.bytes_written}",
            f"- Overwritten: {'yes' if result.overwritten else 'no'}",
        ]
    )


def _write_content_to_file(
    filename: str,
    content: str,
    *,
    file_type: str,
    overwrite: bool,
    write_mode: str,
    ensure_trailing_newline: bool,
    infer_file_type_from_filename: bool = True,
) -> GeneratedFile:
    normalized_mode = _normalize_write_mode(write_mode)
    if normalized_mode == "append":
        if overwrite:
            raise ValueError("overwrite is only supported with write_mode='write'.")
        return append_generated_file(
            filename,
            content,
            file_type=file_type,
            ensure_trailing_newline=ensure_trailing_newline,
            infer_file_type_from_filename=infer_file_type_from_filename,
        )

    return write_generated_file(
        filename,
        content,
        file_type=file_type,
        overwrite=overwrite,
        ensure_trailing_newline=ensure_trailing_newline,
        infer_file_type_from_filename=infer_file_type_from_filename,
    )


def _normalize_write_mode(write_mode: str) -> str:
    normalized = (write_mode or "write").strip().lower()
    if normalized == "chunk":
        return "append"
    if normalized not in {"write", "append"}:
        raise ValueError("write_mode must be 'write' or 'append'.")
    return normalized


def _validate_min_words(content: str, min_words: int) -> None:
    if min_words <= 0:
        return
    words = _word_count(content)
    if words >= min_words:
        return
    raise ValueError(
        f"Content is too short for this file: {words} words provided, but at least {min_words} words are required. "
        "Expand the content with fuller sections, examples, details, and a conclusion, then call the file tool again."
    )


def _word_count(content: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", content or ""))


def _format_generated_file_result(result: GeneratedFile) -> str:
    label = "PDF" if result.file_type == "pdf" else "Markdown"
    message = f"{label} file appended." if result.operation == "append" else f"{label} file generated."
    return "\n".join(
        [
            message,
            f"- Path: {result.path}",
            f"- File type: {result.file_type}",
            f"- Write mode: {result.operation}",
            f"- Characters written: {result.characters_written}",
            f"- Bytes written: {result.bytes_written}",
            f"- Overwritten: {'yes' if result.overwritten else 'no'}",
        ]
    )


def _format_search_file_section(
    *,
    query: str,
    instance_url: str,
    results: list[searxng.SearchResult],
    answers: list[str],
    suggestions: list[str],
) -> str:
    title = " ".join(query.split())
    search_markdown = format_search_response(
        query=query,
        instance_url=instance_url,
        results=results,
        answers=answers,
        suggestions=suggestions,
    )
    return "\n".join([f"## Web Search: {title}", "", search_markdown])
